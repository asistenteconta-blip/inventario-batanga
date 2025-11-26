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
# HOJAS / CONFIG GENERAL
# =========================================================

BD_TAB = "BD_productos"
INV_CO = "INVENTARIO_COCINA"
INV_SU = "INVENTARIO_SUMINISTROS"
INV_BA = "INVENTARIO_BARRA"

HEADER_ROW = 4
DATA_START = 5

if "confirm_reset" not in st.session_state:
    st.session_state["confirm_reset"] = False


# =========================================================
# CARGA BASE DE PRODUCTOS
# =========================================================

@st.cache_data(show_spinner=False)
def load_bd():
    ws = doc.worksheet(BD_TAB)
    raw = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
    df = pd.DataFrame(raw[1:], columns=raw[0])

    df.columns = df.columns.str.upper().str.strip()

    for c in ["PRECIO NETO", "COSTO X UNIDAD", "CANTIDAD DE UNIDAD DE MEDIDA"]:
        if c in df.columns:
            df[c] = df[c].astype(str).str.replace(",", "")
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

    return df

df = load_bd()


# =========================================================
# FUNCIONES GOOGLE SHEETS
# =========================================================

def colletter(n:int)->str:
    s=""; 
    while n>0:
        n,r=divmod(n-1,26); s=chr(r+65)+s
    return s

def get_sheet(area):
    hojas={ws.title.upper():ws for ws in doc.worksheets()}
    a=area.upper()
    if a=="COCINA": return hojas.get(INV_CO.upper())
    if a in("SUMINISTROS","CONSUMIBLE"): return hojas.get(INV_SU.upper())
    if a=="BARRA": return hojas.get(INV_BA.upper())
    st.error("Área inválida"); st.stop()

def get_headers(ws):    
    header=ws.row_values(HEADER_ROW)
    return { str(h).strip().upper():i for i,h in enumerate(header,start=1) if str(h).strip() }

def get_rows(ws,col):
    vals=ws.col_values(col)
    return { vals[i-1].strip().upper():i for i in range(DATA_START,len(vals)+1) if vals[i-1]!="" }


# =========================================================
# UI PRINCIPAL
# =========================================================

st.title("📦 Inventario Diario — Batanga")

st.warning("""
⚠ Validar cantidades ANTES de guardar.
⚠ RESET borra inventario del área + comentario en C3.
⚠ Google Sheets calcula automáticamente el valor final.
""")

fecha=st.date_input("Fecha:",value=date.today())
fecha_str=fecha.strftime("%d-%m-%Y")


# ================= FILTROS =================

areas=sorted([a for a in df["ÁREA"].unique() if a.upper()!="GASTO"])
area=st.selectbox("Área:",areas)

df_area=df[df["ÁREA"]==area]

categoria=st.selectbox("Categoría:",sorted(df_area["CATEGORIA"].unique()))
df_cat=df_area[df_area["CATEGORIA"]==categoria]

subs=["TODOS"]+sorted(df_cat["SUB FAMILIA"].unique())
subfam=st.selectbox("Subfamilia:",subs)

df_sf=df_cat if subfam=="TODOS" else df_cat[df_cat["SUB FAMILIA"]==subfam]

prods=["TODOS"]+sorted(df_sf["PRODUCTO GENÉRICO"].unique())
prod_sel=st.selectbox("Producto específico:",prods)

df_sel=df_sf if prod_sel=="TODOS" else df_sf[df_sf["PRODUCTO GENÉRICO"]==prod_sel]

if df_sel.empty: st.stop()


# =========================================================
# 🔥💥 TABLA CON MEMORIA SIN DOBLE INGRESO 💥🔥
# =========================================================

key=f"tabla|{area}|{categoria}|{subfam}|{prod_sel}"

df_new=pd.DataFrame({
    "PRODUCTO":df_sel["PRODUCTO GENÉRICO"].tolist(),
    "UNIDAD":df_sel["UNIDAD RECETA"].tolist(),
    "MEDIDA":df_sel["CANTIDAD DE UNIDAD DE MEDIDA"].tolist(),
    "CERRADO":[0.0]*len(df_sel),
    "ABIERTO(PESO)":[0.0]*len(df_sel),
    "BOTELLAS_ABIERTAS":[0.0 if area.upper()=="BARRA" else ""]*len(df_sel)
})

# si existe memoria → fusiona y respeta avances
if key in st.session_state:
    df_old=st.session_state[key]
    for col in df_new.columns:
        if col in df_old.columns:
            df_new[col]=df_old[col].values

# editor usando tabla persistente instantánea (adiós doble ingreso)
st.session_state[key]=df_new.copy()

st.subheader("Ingresar inventario")
df_edit = st.data_editor(
    df_new,
    key=f"EDIT_{key}",
    use_container_width=True,
    disabled=["PRODUCTO","UNIDAD","MEDIDA"]
)

# guardar cambios en memoria inmediato 🔥
st.session_state[key]=df_edit.copy()


# =========================================================
# VISTA PREVIA
# =========================================================

merge=df_sel[["PRODUCTO GENÉRICO","PRECIO NETO","COSTO X UNIDAD"]].rename(columns={"PRODUCTO GENÉRICO":"PRODUCTO"})
prev=df_edit.merge(merge,on="PRODUCTO",how="left")

prev["VALOR INVENTARIO (PREVIO)"]=(
    prev["PRECIO NETO"]*prev["CERRADO"]+
    prev["COSTO X UNIDAD"]*prev["ABIERTO(PESO)"]
).round(2)

flt=(prev["CERRADO"]!=0)|(prev["ABIERTO(PESO)"]!=0)
if area.upper()=="BARRA": flt|=(prev["BOTELLAS_ABIERTAS"]!=0)

preview=prev[flt]
st.dataframe(preview,use_container_width=True) if not preview.empty else st.info("Sin valores cargados.")


# =========================================================
# GUARDAR EN GOOGLE SHEETS — No modifica fórmulas
# =========================================================

ws=get_sheet(area)
h=get_headers(ws)
rows=get_rows(ws,h["PRODUCTO GENÉRICO"])

colC=h.get("CANTIDAD CERRADO"); colA=h.get("CANTIDAD ABIERTO (PESO)")
colB=h.get("CANTIDAD BOTELLAS ABIERTAS"); colF=h.get("FECHA")

def guardar_inventario():
    upd=[]
    for _,r in preview.iterrows():
        p=r["PRODUCTO"].upper()
        if p not in rows: continue
        rw=rows[p]

        if colC: upd.append({"range":f"{colletter(colC)}{rw}","values":[[float(r['CERRADO'])]]})
        if colA: upd.append({"range":f"{colletter(colA)}{rw}","values":[[float(r['ABIERTO(PESO)'])]]})
        if area.upper()=="BARRA" and colB:
            try: v=float(r["BOTELLAS_ABIERTAS"])
            except: v=0
            upd.append({"range":f"{colletter(colB)}{rw}","values":[[v]]})
        if colF: upd.append({"range":f"{colletter(colF)}{rw}","values":[[fecha_str]]})

    if upd: ws.batch_update(upd)


# =========================================================
# RESET
# =========================================================

def reset_inventario():
    upd=[]
    for rw in rows.values():
        if colC: upd.append({"range":f"{colletter(colC)}{rw}","values":[[0]]})
        if colA: upd.append({"range":f"{colletter(colA)}{rw}","values":[[0]]})
        if colB: upd.append({"range":f"{colletter(colB)}{rw}","values":[[0]]})
        if colF: upd.append({"range":f"{colletter(colF)}{rw}","values":[[""]]})
    upd.append({"range":"C3","values":[[""]]})
    if upd: ws.batch_update(upd)

    # limpiar memoria área actual
    for k in list(st.session_state.keys()):
        if k.startswith(f"tabla|{area}|"): del st.session_state[k]
    st.session_state.pop("comentario_texto",None)


# =========================================================
# COMENTARIO
# =========================================================

st.subheader("Comentario general (C3)")
coment=st.text_area("",key="comentario_texto")

if st.button("💬 Guardar comentario"):
    ws.update("C3",[[coment]])
    st.success("Comentario guardado ✔")


# =========================================================
# BOTONES
# =========================================================

c1,c2=st.columns(2)

with c1:
    if st.button("💾 Guardar Inventario"):
        guardar_inventario()
        st.success("Guardado correctamente ✔")

with c2:
    if st.button("🧹 Reset"):
        st.session_state["confirm_reset"]=True

if st.session_state["confirm_reset"]:
    st.error(f"¿Confirmar RESET del área {area}?")
    a,b=st.columns(2)
    with a:
        if st.button("SI, BORRAR TODO"):
            reset_inventario()
            st.success("Inventario y comentario reseteados ✔")
            st.session_state["confirm_reset"]=False
    with b:
        if st.button("Cancelar"):
            st.session_state["confirm_reset"]=False
            st.info("Cancelado.")
