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
#   🧠 CARRITO GLOBAL (Valores guardados aunque cambies área)
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
#  HOJAS DESTINO SEGÚN ÁREA
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
    s=""; 
    while n>0: n,r=divmod(n-1,26); s=chr(r+65)+s
    return s


# =========================================================
#  UI
# =========================================================
st.title("📦 Sistema Inventario Batanga / Aguizotes")

st.warning("⚠ Revise la vista previa antes de guardar. El reset borra TODO del área + comentario.")


fecha = st.date_input("Fecha de inventario:",value=date.today())
fecha_str = fecha.strftime("%d-%m-%Y")

st.markdown("### Selección de productos")

# ========= filtros =========
areas = sorted([a for a in df["ÁREA"].unique() if str(a).upper() != "GASTO"])
area = st.selectbox("Área:",areas)

df_area = df[df["ÁREA"]==area]
categoria = st.selectbox("Categoría:", sorted(df_area["CATEGORIA"].unique()))
df_cat = df_area[df_area["CATEGORIA"]==categoria]

subfams = ["TODOS"]+sorted(df_cat["SUB FAMILIA"].unique())
subfam = st.selectbox("Subfamilia:",subfams)
df_sf = df_cat if subfam=="TODOS" else df_cat[df_cat["SUB FAMILIA"]==subfam]

prods = ["TODOS"]+sorted(df_sf["PRODUCTO GENÉRICO"].unique())
prod_sel = st.selectbox("Producto específico:",prods)

df_sel = df_sf if prod_sel=="TODOS" else df_sf[df_sf["PRODUCTO GENÉRICO"]==prod_sel]


# =========================================================
#   TABLA EDITABLE (CARRITO ACTIVO)
# =========================================================
tabla=[]
for p in df_sel["PRODUCTO GENÉRICO"]:
    key=(area,p.upper())
    mem=st.session_state["carrito"].get(key,{})
    row=df_sel[df_sel["PRODUCTO GENÉRICO"]==p]

    tabla.append({
        "PRODUCTO":p,
        "UNIDAD":row["UNIDAD RECETA"].values[0],
        "MEDIDA":row["CANTIDAD DE UNIDAD DE MEDIDA"].values[0],
        "CERRADO":mem.get("CERRADO",0),
        "ABIERTO(PESO)":mem.get("ABIERTO(PESO)",0),
        "BOTELLAS_ABIERTAS":mem.get("BOTELLAS_ABIERTAS",0) if area.upper()=="BARRA" else ""
    })

df_edit=pd.DataFrame(tabla)

editable=["CERRADO","ABIERTO(PESO)"]
if area.upper()=="BARRA": editable+=["BOTELLAS_ABIERTAS"]

st.subheader("Ingresar cantidades:")
df_edit = st.data_editor(df_edit,use_container_width=True,disabled=[c for c in df_edit if c not in editable])

# guardar en memoria interna
for _,r in df_edit.iterrows():
    key=(area,r["PRODUCTO"].upper())
    st.session_state["carrito"][key]={
        "CERRADO":float(r["CERRADO"]),
        "ABIERTO(PESO)":float(r["ABIERTO(PESO)"]),
    }
    if area.upper()=="BARRA": 
        st.session_state["carrito"][key]["BOTELLAS_ABIERTAS"]=float(r["BOTELLAS_ABIERTAS"])


# =========================================================
#   VISTA PREVIA (solo productos con valores > 0)
# =========================================================
st.subheader("Vista Previa")

merge=df_sel[["PRODUCTO GENÉRICO","PRECIO NETO","COSTO X UNIDAD"]]
merge=merge.rename(columns={"PRODUCTO GENÉRICO":"PRODUCTO"})

prev= df_edit.merge(merge,on="PRODUCTO")
prev["VALOR INVENTARIO"]=prev["PRECIO NETO"]*prev["CERRADO"]+prev["COSTO X UNIDAD"]*prev["ABIERTO(PESO)"]
prev["VALOR INVENTARIO"]=prev["VALOR INVENTARIO"].round(2)

filtro=(prev["CERRADO"]!=0)|(prev["ABIERTO(PESO)"]!=0)
if area.upper()=="BARRA": filtro |= (prev["BOTELLAS_ABIERTAS"]!=0)

prev=prev[filtro]

cols=["PRODUCTO","CERRADO","ABIERTO(PESO)"]
if area.upper()=="BARRA": cols+=["BOTELLAS_ABIERTAS"]
cols+=["VALOR INVENTARIO"]

st.dataframe(prev[cols],use_container_width=True)


# =========================================================
#   GUARDAR A GOOGLE SHEETS
# =========================================================
ws = get_dest_sheet(area)
m = get_header_map(ws)

cProd=m["PRODUCTO GENÉRICO"]
cCer=m.get("CANTIDAD CERRADO")
cAb=m.get("CANTIDAD ABIERTO (PESO)")
cBot=m.get("CANTIDAD BOTELLAS ABIERTAS")
cFecha=m.get("FECHA")
cValor=m.get("VALOR INVENTARIO")


def guardar():
    updates=[]
    filas=0

    rows=get_product_row_map(ws,cProd)

    for _,r in df_edit.iterrows():
        prod=r["PRODUCTO"].upper()
        if prod not in rows: continue  
        row=rows[prod]

        if cCer:  updates.append({"range":f"{colnum_to_colletter(cCer)}{row}","values":[[float(r['CERRADO'])]]})
        if cAb:   updates.append({"range":f"{colnum_to_colletter(cAb)}{row}","values":[[float(r['ABIERTO(PESO)'])]]})
        if area.upper()=="BARRA" and cBot:
            updates.append({"range":f"{colnum_to_colletter(cBot)}{row}","values":[[float(r['BOTELLAS_ABIERTAS'])]]})

        if cFecha: updates.append({"range":f"{colnum_to_colletter(cFecha)}{row}","values":[[fecha_str]]})

        filas+=1
    
    ws.batch_update(updates)
    return filas


# =========================================================
#   RESET TOTAL + confirmar + borrar comentario
# =========================================================
def reset_inventario():
    rows=get_product_row_map(ws,cProd)
    updates=[]

    for r in rows.values():
        if cCer:  updates.append({"range":f"{colnum_to_colletter(cCer)}{r}","values":[[0]]})
        if cAb:   updates.append({"range":f"{colnum_to_colletter(cAb)}{r}","values":[[0]]})
        if cBot:  updates.append({"range":f"{colnum_to_colletter(cBot)}{r}","values":[[0]]})
        if cValor:updates.append({"range":f"{colnum_to_colletter(cValor)}{r}","values":[[0]]})
        if cFecha:updates.append({"range":f"{colnum_to_colletter(cFecha)}{r}","values":[[""]]})

    updates.append({"range":"C3","values":[[""]]})
    ws.batch_update(updates)

    st.session_state["carrito"]={}
    st.session_state.pop("comentario_texto",None)


# =========================================================
#   COMENTARIO EN C3
# =========================================================
st.subheader("Comentario Inventario")
coment=st.text_area("Comentario:",key="comentario_texto")

if st.button("💬 Guardar comentario en C3"):
    ws.update("C3",[[coment]])
    st.success("Comentario guardado.")


# =========================================================
#   BOTONES FINALES
# =========================================================
c1,c2=st.columns(2)

with c1:
    if st.button("💾 Guardar Inventario"):
        x=guardar()
        st.success(f"✔ Guardado {x} productos correctamente.")


with c2:
    if st.button("🧹 Resetear Inventario"):
        st.session_state["confirm_reset"]=True


if st.session_state["confirm_reset"]:
    st.error("⚠ ¿Seguro quieres BORRAR TODO el inventario del área + comentario?",icon="⚠")
    cc1,cc2=st.columns(2)

    with cc1:
        if st.button("CONFIRMAR RESET"):
            reset_inventario()
            st.success("Inventario y comentario borrados.")
            st.session_state["confirm_reset"]=False

    with cc2:
        if st.button("Cancelar"):
            st.session_state["confirm_reset"]=False
            st.info("Operación cancelada.")

