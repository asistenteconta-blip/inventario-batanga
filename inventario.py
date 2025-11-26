import streamlit as st
import pandas as pd
import gspread
from datetime import date
from google.oauth2.service_account import Credentials

# =========================================================
# 🔥 CONFIG GOOGLE SHEETS
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
def get_doc(): return client.open(DOC_NAME)

doc = get_doc()

# =========================================================
# HOJAS / CONFIG
# =========================================================
BD_TAB="BD_productos"
INV_CO="INVENTARIO_COCINA"
INV_SU="INVENTARIO_SUMINISTROS"
INV_BA="INVENTARIO_BARRA"

HEADER_ROW = 4
DATA_START = 5

if "confirm_reset" not in st.session_state:
    st.session_state["confirm_reset"]=False

if "memory" not in st.session_state:
    st.session_state["memory"]={}  # memoria por área/categoría/subfamilia/producto

# =========================================================
# BASE DE DATOS
# =========================================================
@st.cache_data(show_spinner=False)
def load_bd():
    ws=doc.worksheet(BD_TAB)
    raw=ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
    df=pd.DataFrame(raw[1:],columns=raw[0])
    df.columns=df.columns.str.upper().str.strip()

    for c in ["PRECIO NETO","COSTO X UNIDAD","CANTIDAD DE UNIDAD DE MEDIDA"]:
        df[c]=pd.to_numeric(df[c].astype(str).str.replace(",",""), errors="coerce").fillna(0)

    return df

df=load_bd()

# =========================================================
# FUNCIONES GOOGLE SHEETS
# =========================================================
def colletter(n):
    s=""
    while n>0: n,r=divmod(n-1,26); s=chr(r+65)+s
    return s

def get_sheet(area):
    area=area.upper()
    hojas={ws.title.upper():ws for ws in doc.worksheets()}
    if area=="COCINA": return hojas[INV_CO.upper()]
    if area in("SUMINISTROS","CONSUMIBLE"): return hojas[INV_SU.upper()]
    if area=="BARRA": return hojas[INV_BA.upper()]
    st.stop()

def get_headers(ws):
    return {h.strip().upper():i for i,h in enumerate(ws.row_values(HEADER_ROW),start=1) if h.strip()}

def get_rows(ws,col_prod):
    vals=ws.col_values(col_prod)
    return {vals[i-1].upper():i for i in range(DATA_START,len(vals)+1) if vals[i-1]!="""}

# =========================================================
# UI
# =========================================================
st.title("📦 Sistema Inventario Batanga")

st.warning("""
⚠ Validar cantidades antes de guardar.
⚠ Reset borra inventario + comentario, pero la fórmula se mantiene.
""")


fecha=st.date_input("Fecha:",value=date.today())
fecha_str=fecha.strftime("%d-%m-%Y")

# ====== FILTROS ======
areas=sorted([x for x in df["ÁREA"].unique() if x.upper()!="GASTO"])
area=st.selectbox("Área:",areas)

df_area=df[df["ÁREA"]==area]
categoria=st.selectbox("Categoría:",sorted(df_area["CATEGORIA"].unique()))
df_cat=df_area[df_area["CATEGORIA"]==categoria]

subfams=["TODOS"]+sorted(df_cat["SUB FAMILIA"].unique())
subfam=st.selectbox("Subfamilia:",subfams)
df_sf=df_cat if subfam=="TODOS" else df_cat[df_cat["SUB FAMILIA"]==subfam]

prods=["TODOS"]+sorted(df_sf["PRODUCTO GENÉRICO"].unique())
prod_sel=st.selectbox("Producto específico:",prods)
df_sel=df_sf if prod_sel=="TODOS" else df_sf[df_sf["PRODUCTO GENÉRICO"]==prod_sel]

if df_sel.empty: st.stop()

# =========================================================
# 🔥 TABLA CON MEMORIA REAL (NO SE BORRA EL PRIMER INPUT)
# =========================================================
mem_key=f"{area}|{categoria}|{subfam}|{prod_sel}"

if mem_key not in st.session_state["memory"]:
    st.session_state["memory"][mem_key]=pd.DataFrame({
        "PRODUCTO":df_sel["PRODUCTO GENÉRICO"].values,
        "UNIDAD":df_sel["UNIDAD RECETA"].values,
        "MEDIDA":df_sel["CANTIDAD DE UNIDAD DE MEDIDA"].values,
        "CERRADO":[0.0]*len(df_sel),
        "ABIERTO(PESO)":[0.0]*len(df_sel),
        "BOTELLAS_ABIERTAS":[0.0 if area.upper()=="BARRA" else ""]*len(df_sel)
    })

df_edit=st.session_state["memory"][mem_key].copy()

# 🔥 TIPADO NUMÉRICO → elimina por completo el doble ingreso
for col in ["CERRADO","ABIERTO(PESO)","BOTELLAS_ABIERTAS"]:
    if col in df_edit.columns:
        df_edit[col]=pd.to_numeric(df_edit[col],errors="coerce").fillna(0.0)

df_edit = st.data_editor(
    df_edit,
    key=f"ED_{mem_key}",
    use_container_width=True,
    disabled=["PRODUCTO","UNIDAD","MEDIDA"]
)

st.session_state["memory"][mem_key]=df_edit.copy()  # se guarda al instante

# =========================================================
# VISTA PREVIA
# =========================================================
merge=df_sel[["PRODUCTO GENÉRICO","PRECIO NETO","COSTO X UNIDAD"]].rename(columns={"PRODUCTO GENÉRICO":"PRODUCTO"})
prev=df_edit.merge(merge,on="PRODUCTO",how="left")
prev["VALOR INVENTARIO"]=(prev["PRECIO NETO"]*prev["CERRADO"])+(prev["COSTO X UNIDAD"]*prev["ABIERTO(PESO)"])
prev["VALOR INVENTARIO"]=prev["VALOR INVENTARIO"].round(2)

filtro=(prev["CERRADO"]>0)|(prev["ABIERTO(PESO)"]>0)
if area.upper()=="BARRA": filtro|=(prev["BOTELLAS_ABIERTAS"]>0)

prev=prev[filtro]
st.dataframe(prev,use_container_width=True)

# =========================================================
# MAPEOS GOOGLE SHEETS
# =========================================================
ws=get_sheet(area)
h=get_headers(ws)
rows=get_rows(ws,h["PRODUCTO GENÉRICO"])

cCer=h.get("CANTIDAD CERRADO")
cAb=h.get("CANTIDAD ABIERTO (PESO)")
cBot=h.get("CANTIDAD BOTELLAS ABIERTAS")
cFecha=h.get("FECHA")

# =========================================================
# 💾 GUARDAR
# =========================================================
def guardar():
    updates=[]
    for _,r in prev.iterrows():
        prod=r["PRODUCTO"].upper()
        if prod not in rows: continue
        row=rows[prod]

        if cCer: updates.append({"range":f"{colletter(cCer)}{row}","values":[[r['CERRADO']]]})
        if cAb: updates.append({"range":f"{colletter(cAb)}{row}","values":[[r['ABIERTO(PESO)']]]})
        if area.upper()=="BARRA" and cBot:
            updates.append({"range":f"{colletter(cBot)}{row}","values":[[r['BOTELLAS_ABIERTAS']]]})
        if cFecha:
            updates.append({"range":f"{colletter(cFecha)}{row}","values":[[fecha_str]]})

    if updates: ws.batch_update(updates)

# =========================================================
# RESET
# =========================================================
def reset_inventario():
    updates=[]
    for r in rows.values():
        if cCer: updates.append({"range":f"{colletter(cCer)}{r}","values":[[0]]})
        if cAb: updates.append({"range":f"{colletter(cAb)}{r}","values":[[0]]})
        if cBot: updates.append({"range":f"{colletter(cBot)}{r}","values":[[0]]})
        if cFecha: updates.append({"range":f"{colletter(cFecha)}{r}","values":[[""]]]})

    updates.append({"range":"C3","values":[[""]]})
    ws.batch_update(updates)

    st.session_state.pop("comentario_texto",None)

# =========================================================
# COMENTARIO
# =========================================================
coment=st.text_area("Comentario general (C3)",key="comentario_texto")
if st.button("💬 Guardar comentario en C3"):
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
    st.error("⚠ ¿CONFIRMAR RESET?",icon="⚠")
    c3,c4=st.columns(2)
    with c3:
        if st.button("SÍ, BORRAR TODO"):
            reset_inventario()
            st.success("Inventario reseteado ✔")
            st.session_state["confirm_reset"]=False
    with c4:
        if st.button("Cancelar"):
            st.session_state["confirm_reset"]=False
            st.info("Cancelado.")
