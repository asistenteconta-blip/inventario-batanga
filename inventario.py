import streamlit as st
import pandas as pd
import gspread
from datetime import date
from google.oauth2.service_account import Credentials

# =========================================================
#  CONFIG GOOGLE SHEETS
# =========================================================

scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

DOC_NAME = "Copia de MACHOTE INV BATANGA DDMMAAAA  ACT25"

service_info = st.secrets["google_service_account"]
credentials = Credentials.from_service_account_info(service_info, scopes=scope)
client = gspread.authorize(credentials)

@st.cache_resource(show_spinner=False)
def get_doc():
    return client.open(DOC_NAME)

doc = get_doc()

# =========================================================
# HOJAS
# =========================================================

BD_TAB = "BD_productos"
INV_CO = "INVENTARIO_COCINA"
INV_SU = "INVENTARIO_SUMINISTROS"
INV_BA = "INVENTARIO_BARRA"

HEADER_ROW = 4
DATA_START = 5

# =========================================================
# BASE DE DATOS PRINCIPAL
# =========================================================

@st.cache_data(show_spinner=False)
def load_bd():
    ws = doc.worksheet(BD_TAB)
    raw = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
    df = pd.DataFrame(raw[1:], columns=[h.strip() for h in raw[0]])
    df.columns = df.columns.str.upper().str.strip()

    numeric = ["PRECIO NETO","COSTO X UNIDAD","CANTIDAD DE UNIDAD DE MEDIDA"]
    for c in numeric:
        df[c] = pd.to_numeric(df[c].astype(str).str.replace(",",""), errors="coerce").fillna(0)

    return df

df = load_bd()

def colletter(n):
    s=""
    while n>0:n,r=divmod(n-1,26);s=chr(r+65)+s
    return s

def get_sheet(area):
    area=area.upper()
    hojas={ws.title.upper():ws for ws in doc.worksheets()}

    if area=="COCINA":return hojas[INV_CO.upper()]
    if area in("CONSUMIBLE","SUMINISTROS"):return hojas[INV_SU.upper()]
    if area=="BARRA":return hojas[INV_BA.upper()]

    st.error("Área inválida");st.stop()

def get_headers(ws):
    row=ws.row_values(HEADER_ROW)
    return {r.strip().upper():i for i,r in enumerate(row,start=1) if r.strip()}

def get_rows(ws, col):
    vals = ws.col_values(col)
    return {
        str(vals[i-1]).upper(): i
        for i in range(DATA_START, len(vals)+1)
        if str(vals[i-1]).strip() != ""
    }


# =========================================================
# UI
# =========================================================

st.title("📦 Sistema Inventario Batanga")
fecha=st.date_input("Fecha",value=date.today())
fstr=fecha.strftime("%d-%m-%Y")

# FILTROS
areas=sorted([x for x in df["ÁREA"].unique() if x.upper()!="GASTO"])
area=st.selectbox("Área",areas)

df_area=df[df["ÁREA"]==area]
categoria=st.selectbox("Categoría",sorted(df_area["CATEGORIA"].unique()))

df_cat=df_area[df_area["CATEGORIA"]==categoria]
subfams=["TODOS"]+sorted(df_cat["SUB FAMILIA"].unique())
subfam=st.selectbox("Subfamilia",subfams)

df_sf=df_cat if subfam=="TODOS" else df_cat[df_cat["SUB FAMILIA"]==subfam]

prods=["TODOS"]+sorted(df_sf["PRODUCTO GENÉRICO"].unique())
prod_sel=st.selectbox("Producto",prods)

df_sel=df_sf if prod_sel=="TODOS" else df_sf[df_sf["PRODUCTO GENÉRICO"]==prod_sel]

# =========================================================
# TABLA EDITABLE (sin memoria, sin carrito)
# =========================================================

st.subheader("Ingresar inventario (Directo y estable)")

tabla = pd.DataFrame({
    "PRODUCTO":df_sel["PRODUCTO GENÉRICO"].values,
    "UNIDAD":df_sel["UNIDAD RECETA"].values,
    "MEDIDA":df_sel["CANTIDAD DE UNIDAD DE MEDIDA"].values,
    "CERRADO":[0.0]*len(df_sel),
    "ABIERTO(PESO)":[0.0]*len(df_sel),
    "BOTELLAS_ABIERTAS":[0.0]*len(df_sel) if area.upper()=="BARRA" else ["" for _ in range(len(df_sel))]
})

df_edit = st.data_editor(
    tabla,
    use_container_width=True,
    disabled=["PRODUCTO","UNIDAD","MEDIDA"],
)

# =========================================================
# VISTA PREVIA
# =========================================================

st.subheader("Vista previa")

merge=df_sel[["PRODUCTO GENÉRICO","PRECIO NETO","COSTO X UNIDAD"]].rename(
    columns={"PRODUCTO GENÉRICO":"PRODUCTO"}
)

prev=df_edit.merge(merge,on="PRODUCTO")

prev["VALOR INVENTARIO"]=(prev["PRECIO NETO"]*prev["CERRADO"])+(prev["COSTO X UNIDAD"]*prev["ABIERTO(PESO)"])
prev["VALOR INVENTARIO"]=prev["VALOR INVENTARIO"].round(2)

mask = (prev["CERRADO"]!=0)|(prev["ABIERTO(PESO)"]!=0)
if area.upper()=="BARRA":
    mask|=(prev["BOTELLAS_ABIERTAS"]!=0)

prev=prev[mask]

cols=["PRODUCTO","CERRADO","ABIERTO(PESO)"]
if area.upper()=="BARRA":cols.append("BOTELLAS_ABIERTAS")
cols.append("VALOR INVENTARIO")

st.dataframe(prev[cols],use_container_width=True)

# =========================================================
# GUARDAR A SHEETS
# =========================================================

ws=get_sheet(area)
head=get_headers(ws)
rows=get_rows(ws,head["PRODUCTO GENÉRICO"])

cC=head.get("CANTIDAD CERRADO")
cA=head.get("CANTIDAD ABIERTO (PESO)")
cB=head.get("CANTIDAD BOTELLAS ABIERTAS")
cF=head.get("FECHA")
cV=head.get("VALOR INVENTARIO")

def save():
    updates=[]
    for _,r in prev.iterrows():
        prod=r["PRODUCTO"].upper()
        if prod not in rows:continue
        row=rows[prod]

        if cC:updates.append({"range":f"{colletter(cC)}{row}","values":[[r['CERRADO']]]})
        if cA:updates.append({"range":f"{colletter(cA)}{row}","values":[[r['ABIERTO(PESO)']]]})
        if area.upper()=="BARRA" and cB:
            updates.append({"range":f"{colletter(cB)}{row}","values":[[r['BOTELLAS_ABIERTAS']]]})
        if cF:updates.append({"range":f"{colletter(cF)}{row}","values":[[fstr]]})

    if updates: ws.batch_update(updates)

# =========================================================
# RESET
# =========================================================

def reset():
    updates=[]
    for r in rows.values():
        if cC:updates.append({"range":f"{colletter(cC)}{r}","values":[[0]]})
        if cA:updates.append({"range":f"{colletter(cA)}{r}","values":[[0]]})
        if cB:updates.append({"range":f"{colletter(cB)}{r}","values":[[0]]})
        if cV:updates.append({"range":f"{colletter(cV)}{r}","values":[[0]]})
        if cF:updates.append({"range":f"{colletter(cF)}{r}","values":[[""]]})

    # comentario C3
    updates.append({"range":"C3","values":[[""]]})

    ws.batch_update(updates)

# =========================================================
# BOTONES
# =========================================================

col1,col2=st.columns(2)

with col1:
    if st.button("💾 GUARDAR INVENTARIO"):
        save();st.success("Guardado ✔")

with col2:
    if st.button("🧹 RESET"):
        reset();st.success("Inventario borrado")

