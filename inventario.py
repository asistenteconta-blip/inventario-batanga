import streamlit as st
import pandas as pd
import gspread
from datetime import date
from google.oauth2.service_account import Credentials

# =========================================================
# CONFIG GOOGLE SHEETS
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
# CARGA BASE
# =========================================================

@st.cache_data
def load_bd():
    ws = doc.worksheet(BD_TAB)
    raw = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
    df = pd.DataFrame(raw[1:], columns=raw[0])

    df.columns = df.columns.str.upper().str.strip()

    for c in ["PRECIO NETO","COSTO X UNIDAD","CANTIDAD DE UNIDAD DE MEDIDA"]:
        df[c] = pd.to_numeric(df[c].astype(str).str.replace(",",""),errors="coerce").fillna(0)

    return df

df = load_bd()


# =========================================================
# FUNCIONES GOOGLE SHEETS
# =========================================================

def colletter(n):
    s=""
    while n>0:
        n,r=divmod(n-1,26)
        s=chr(r+65)+s
    return s

def get_sheet(area):
    area=area.upper()
    sheets={ws.title.upper():ws for ws in doc.worksheets()}
    if area=="COCINA": return sheets[INV_CO.upper()]
    if area in("SUMINISTROS","CONSUMIBLE"): return sheets[INV_SU.upper()]
    if area=="BARRA": return sheets[INV_BA.upper()]
    st.stop()

def get_headers(ws):
    return{h.strip().upper():i for i,h in enumerate(ws.row_values(HEADER_ROW),start=1) if h.strip()}

def get_rows(ws,col):
    vals=ws.col_values(col)
    return{vals[i-1].upper():i for i in range(DATA_START,len(vals)+1) if vals[i-1]!=""}


# =========================================================
# UI PRINCIPAL
# =========================================================

st.title("📦 Inventario Diario — Batanga")
fecha=date.today()
fecha_str=fecha.strftime("%d-%m-%Y")

st.warning("📌 Los datos NO se guardan al cambiar categoría.\n📌 La Vista Previa es el registro global de inventario.")


# =========================================================
# FILTROS
# =========================================================

areas=sorted([x for x in df["ÁREA"].unique() if x.upper()!="GASTO"])
area=st.selectbox("Área:",areas)

cats=sorted(df[df["ÁREA"]==area]["CATEGORIA"].unique())
categoria=st.selectbox("Categoría:",cats)

df_cat=df[(df["ÁREA"]==area)&(df["CATEGORIA"]==categoria)]

subf=["TODOS"]+sorted(df_cat["SUB FAMILIA"].unique())
subfam=st.selectbox("Subfamilia:",subf)

df_sf=df_cat if subfam=="TODOS" else df_cat[df_cat["SUB FAMILIA"]==subfam]

prods=["TODOS"]+sorted(df_sf["PRODUCTO GENÉRICO"].unique())
prod_sel=st.selectbox("Producto:",prods)

df_sel=df_sf if prod_sel=="TODOS" else df_sf[df_sf["PRODUCTO GENÉRICO"]==prod_sel]


# =========================================================
# TABLA EDITABLE (SIN GUARDAR MEMORIA)
# =========================================================

st.subheader("Ingresar inventario (no persiste al volver)")
tabla=pd.DataFrame({
    "PRODUCTO":df_sel["PRODUCTO GENÉRICO"],
    "UNIDAD":df_sel["UNIDAD RECETA"],
    "MEDIDA":df_sel["CANTIDAD DE UNIDAD DE MEDIDA"],
    "CERRADO":[0.0]*len(df_sel),
    "ABIERTO(PESO)":[0.0]*len(df_sel),
})

if area.upper()=="BARRA":
    tabla["BOTELLAS_ABIERTAS"]=[0.0]*len(df_sel)
else:
    tabla["BOTELLAS_ABIERTAS"]=[""]*len(df_sel)

df_edit = st.data_editor(tabla,use_container_width=True,disabled=["PRODUCTO","UNIDAD","MEDIDA"])


# =========================================================
# VISTA PREVIA GLOBAL (SE GUARDA SOLO AQUÍ)
# =========================================================

st.subheader("📊 Vista Previa Global")

if "preview" not in st.session_state:
    st.session_state["preview"]=pd.DataFrame(columns=df_edit.columns)

# Agrega pero reemplaza productos repetidos
st.session_state["preview"]=pd.concat([st.session_state["preview"],df_edit])
st.session_state["preview"].drop_duplicates("PRODUCTO",keep="last",inplace=True)

prev=st.session_state["preview"]
prev=prev[(prev["CERRADO"]!=0)|(prev["ABIERTO(PESO)"]!=0)]

st.dataframe(prev,use_container_width=True)


# =========================================================
# GUARDAR A SHEETS DESDE VISTA PREVIA
# =========================================================

ws=get_sheet(area)
h=get_headers(ws)
rows=get_rows(ws,h["PRODUCTO GENÉRICO"])

def guardar():
    updates=[]
    for _,r in prev.iterrows():
        p=r["PRODUCTO"].upper()
        if p not in rows: continue
        row=rows[p]

        updates.append({"range":f"{colletter(h['CANTIDAD CERRADO'])}{row}","values":[[float(r['CERRADO'])]]})
        updates.append({"range":f"{colletter(h['CANTIDAD ABIERTO (PESO)'])}{row}","values":[[float(r['ABIERTO(PESO)'])]]})
        updates.append({"range":f"{colletter(h['FECHA'])}{row}","values":[[fecha_str]]})

    ws.batch_update(updates)
    st.success("✔ Guardado exitoso desde Vista Previa")


st.button("💾 GUARDAR INVENTARIO",on_click=guardar)
