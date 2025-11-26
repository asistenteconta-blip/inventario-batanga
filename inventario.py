import streamlit as st
import pandas as pd
import gspread
from datetime import date
from google.oauth2.service_account import Credentials

# =========================================================
#  CONFIGURACIÓN GOOGLE SHEETS
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

BD_TAB = "BD_productos"
INV_CO = "INVENTARIO_COCINA"
INV_SU = "INVENTARIO_SUMINISTROS"
INV_BA = "INVENTARIO_BARRA"

HEADER_ROW = 4
FIRST_DATA_ROW = 5

# =========================================================
#   🧠 CARRITO GLOBAL
# =========================================================
if "carrito" not in st.session_state:
    st.session_state["carrito"] = {}
if "confirm_reset" not in st.session_state:
    st.session_state["confirm_reset"] = False

# =========================================================
#  BASE DE DATOS PRINCIPAL
# =========================================================
@st.cache_data(show_spinner=False)
def get_bd_df_cached():
    ws = doc.worksheet(BD_TAB)
    raw = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
    headers = [h.strip() for h in raw[0]]
    df = pd.DataFrame(raw[1:], columns=headers)

    df.columns = df.columns.str.strip().str.upper()
    numeric = ["PRECIO NETO","CANTIDAD DE UNIDAD DE MEDIDA","COSTO X UNIDAD"]
    for col in numeric:
        df[col] = pd.to_numeric(df[col].astype(str).str.replace(",",""),errors="coerce").fillna(0)

    return df

df = get_bd_df_cached()

# =========================================================
#  HOJAS DESTINO
# =========================================================
def get_dest_sheet(area):
    hojas = {ws.title.upper(): ws for ws in doc.worksheets()}
    area = area.upper()

    if area=="COCINA": return hojas[INV_CO.upper()]
    if area in ("CONSUMIBLE","SUMINISTROS"): return hojas[INV_SU.upper()]
    if area=="BARRA": return hojas[INV_BA.upper()]

    st.error("Área inválida"); st.stop()


def get_header_map(ws):
    header = ws.row_values(HEADER_ROW)
    return {h.strip().upper():i for i,h in enumerate(header,start=1) if h.strip()}


def get_product_row_map(ws, col):
    col_vals = ws.col_values(col)
    return {str(col_vals[i-1]).upper():i for i in range(FIRST_DATA_ROW,len(col_vals)+1)}


def colnum_to_colletter(n):
    s=""
    while n>0: n,r=divmod(n-1,26); s=chr(r+65)+s
    return s

# =========================================================
# UI
# =========================================================
st.title("📦 Sistema Inventario Batanga / Aguizotes")
st.warning("⚠ Revisar vista previa antes de guardar. Reset borra TODO el inventario + comentario.")

fecha = st.date_input("Fecha:",value=date.today())
fecha_str = fecha.strftime("%d-%m-%Y")

st.markdown("### Selección de productos")

# ========= FILTROS =========
areas = sorted([a for a in df["ÁREA"].unique() if str(a).upper() != "GASTO"])
area = st.selectbox("Área:",areas)

df_area=df[df["ÁREA"]==area]
categoria=st.selectbox("Categoría:",sorted(df_area["CATEGORIA"].unique()))
df_cat=df_area[df_area["CATEGORIA"]==categoria]

subfams=["TODOS"]+sorted(df_cat["SUB FAMILIA"].unique())
subfam=st.selectbox("Subfamilia:",subfams)
df_sf=df_cat if subfam=="TODOS" else df_cat[df_cat["SUB FAMILIA"]==subfam]

prods=["TODOS"]+sorted(df_sf["PRODUCTO GENÉRICO"].unique())
prod_sel=st.selectbox("Producto:",prods)

df_sel=df_sf if prod_sel=="TODOS" else df_sf[df_sf["PRODUCTO GENÉRICO"]==prod_sel]


# =========================================================
# 🔥 TABLA EDITABLE SIN PÉRDIDA DE DATOS
# =========================================================
if f"tabla_{area}" not in st.session_state:  
    filas=[]
    for p in df_sel["PRODUCTO GENÉRICO"]:
        key=(area,p.upper())
        mem=st.session_state["carrito"].get(key,{})
        row=df_sel[df_sel["PRODUCTO GENÉRICO"]==p]

        filas.append({
            "PRODUCTO":p,
            "UNIDAD":row["UNIDAD RECETA"].values[0],
            "MEDIDA":row["CANTIDAD DE UNIDAD DE MEDIDA"].values[0],
            "CERRADO":mem.get("CERRADO",0),
            "ABIERTO(PESO)":mem.get("ABIERTO(PESO)",0),
            "BOTELLAS_ABIERTAS":mem.get("BOTELLAS_ABIERTAS",0) if area.upper()=="BARRA" else ""
        })

    st.session_state[f"tabla_{area}"]=pd.DataFrame(filas)

df_edit=st.session_state[f"tabla_{area}"]

editable=["CERRADO","ABIERTO(PESO)"]
if area.upper()=="BARRA": editable+=["BOTELLAS_ABIERTAS"]

st.subheader("Ingresar cantidades")
df_edit=st.data_editor(df_edit,use_container_width=True,disabled=[c for c in df_edit if c not in editable])

# Guardar cambios en memoria sin perderlos
for i,row in df_edit.iterrows():
    key=(area,row["PRODUCTO"].upper())

    # Manejo seguro incluso si el editor entrega string vacío
    cerrado = float(row["CERRADO"]) if row["CERRADO"] not in ["","None",None] else 0
    abierto = float(row["ABIERTO(PESO)"]) if row["ABIERTO(PESO]"] not in ["","None",None] else 0
    botellas = 0

    if area.upper()=="BARRA":
        try:
            botellas=float(row["BOTELLAS_ABIERTAS"])
        except:
            botellas=0

    st.session_state["carrito"][key]={
        "CERRADO":cerrado,
        "ABIERTO(PESO)":abierto,
        "BOTELLAS_ABIERTAS":botellas if area.upper()=="BARRA" else 0
    }

st.session_state[f"tabla_{area}"]=df_edit


# =========================================================
# VISTA PREVIA
# =========================================================
st.subheader("Vista previa")

merge=df_sel[["PRODUCTO GENÉRICO","PRECIO NETO","COSTO X UNIDAD"]].rename(columns={"PRODUCTO GENÉRICO":"PRODUCTO"})
prev=df_edit.merge(merge,on="PRODUCTO")
prev["VALOR INVENTARIO"]=(prev["PRECIO NETO"]*prev["CERRADO"])+(prev["COSTO X UNIDAD"]*prev["ABIERTO(PESO)"])
prev=prev[ (prev["CERRADO"]!=0)|(prev["ABIERTO(PESO)"]!=0) | ((area.upper()=="BARRA")&(prev["BOTELLAS_ABIERTAS"]!=0)) ]

cols=["PRODUCTO","CERRADO","ABIERTO(PESO)"]
if area.upper()=="BARRA": cols+=["BOTELLAS_ABIERTAS"]
cols+=["VALOR INVENTARIO"]

st.dataframe(prev[cols],use_container_width=True)

# =========================================================
# GUARDAR / RESET
# =========================================================
ws=get_dest_sheet(area)
m=get_header_map(ws)

cProd=m["PRODUCTO GENÉRICO"]
cCer=m.get("CANTIDAD CERRADO")
cAb=m.get("CANTIDAD ABIERTO (PESO)")
cBot=m.get("CANTIDAD BOTELLAS ABIERTAS")
cFecha=m.get("FECHA")
cValor=m.get("VALOR INVENTARIO")

rows=get_product_row_map(ws,cProd)

def guardar():
    updates=[]
    for _,r in df_edit.iterrows():
        prod=r["PRODUCTO"].upper()
        if prod not in rows: continue
        row=rows[prod]

        if cCer: updates.append({"range":f"{colnum_to_colletter(cCer)}{row}","values":[[r["CERRADO"]]]})
        if cAb: updates.append({"range":f"{colnum_to_colletter(cAb)}{row}","values":[[r["ABIERTO(PESO)"]]]})
        if area.upper()=="BARRA" and cBot: updates.append({"range":f"{colnum_to_colletter(cBot)}{row}","values":[[r["BOTELLAS_ABIERTAS"]]]})
        if cFecha: updates.append({"range":f"{colnum_to_colletter(cFecha)}{row}","values":[[fecha_str]]})

    ws.batch_update(updates)

def reset_inventario():
    updates=[]
    for r in rows.values():
        if cCer: updates.append({"range":f"{colnum_to_colletter(cCer)}{r}","values":[[0]]})
        if cAb: updates.append({"range":f"{colnum_to_colletter(cAb)}{r}","values":[[0]]})
        if cBot: updates.append({"range":f"{colnum_to_colletter(cBot)}{r}","values":[[0]]})
        if cValor: updates.append({"range":f"{colnum_to_colletter(cValor)}{r}","values":[[0]]})
        if cFecha: updates.append({"range":f"{colnum_to_colletter(cFecha)}{r}","values":[[""]]})

    updates.append({"range":"C3","values":[[""]]})
    ws.batch_update(updates)

    st.session_state["carrito"]={}
    st.session_state.pop("comentario_texto",None)


# =========================================================
# COMENTARIO C3
# =========================================================
st.subheader("Comentario general")
coment=st.text_area("Comentario:",key="comentario_texto")

if st.button("💬 Guardar comentario"):
    ws.update("C3",[[coment]])
    st.success("Comentario guardado ✔")


# =========================================================
# BOTONES
# =========================================================
c1,c2=st.columns(2)

with c1:
    if st.button("💾 GUARDAR INVENTARIO"):
        guardar()
        st.success("Inventario guardado ✔")

with c2:
    if st.button("🧹 RESET"):
        st.session_state["confirm_reset"]=True

if st.session_state["confirm_reset"]:
    st.error("⚠ ¿Seguro que deseas BORRAR TODO este inventario y comentario?")
    b1,b2=st.columns(2)

    with b1:
        if st.button("CONFIRMAR RESET"):
            reset_inventario()
            st.success("Inventario restaurado")
            st.session_state["confirm_reset"]=False

    with b2:
        if st.button("Cancelar"):
            st.session_state["confirm_reset"]=False
            st.info("Operación cancelada")


