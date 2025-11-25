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
    try:
        return client.open(DOC_NAME)
    except Exception as e:
        st.error(f"❌ No se pudo abrir el documento: {e}")
        st.stop()

doc = get_doc()

BD_TAB = "BD_productos"
INV_CO = "INVENTARIO_COCINA"
INV_SU = "INVENTARIO_SUMINISTROS"
INV_BA = "INVENTARIO_BARRA"

# =========================================================
#   CARRITO GLOBAL (Opción C)
# =========================================================
if "carrito" not in st.session_state:
    st.session_state["carrito"] = {}


# =========================================================
#  FUNCIONES AUXILIARES
# =========================================================

@st.cache_data(show_spinner=False)
def get_bd_df():
    ws = doc.worksheet(BD_TAB)
    raw = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")

    headers = [h.strip() for h in raw[0]]
    df = pd.DataFrame(raw[1:], columns=headers)
    df.columns = df.columns.str.upper()

    num_cols = ["PRECIO NETO", "CANTIDAD DE UNIDAD DE MEDIDA", "COSTO X UNIDAD"]
    for c in num_cols:
        if c in df.columns:
            df[c] = (
                df[c].astype(str)
                .str.replace(" ", "")
                .str.replace(",", "")
            )
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

    return df


def get_dest_sheet(area):
    hojas = {ws.title.upper(): ws for ws in doc.worksheets()}
    area_norm = area.upper()

    if area_norm == "COCINA":
        target = INV_CO.upper()
    elif area_norm in ("CONSUMIBLE", "SUMINISTROS"):
        target = INV_SU.upper()
    elif area_norm == "BARRA":
        target = INV_BA.upper()
    else:
        st.error("❌ Área no válida.")
        st.stop()

    if target not in hojas:
        st.error(f"❌ No existe hoja para: {target}")
        st.stop()

    return hojas[target]


def get_header_map(ws):
    header_row = ws.row_values(4)
    return {
        str(h).strip().upper(): idx
        for idx, h in enumerate(header_row, start=1)
        if str(h).strip()
    }


def get_product_row_map(ws, col_idx_producto):
    col = ws.col_values(col_idx_producto)
    mapping = {}
    for i in range(4, len(col) + 1):
        nombre = str(col[i - 1]).strip().upper()
        if nombre:
            mapping[nombre] = i
    return mapping


def colnum_to_colletter(n):
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(r + ord("A")) + s
    return s


# =========================================================
#  CARGAR BD
# =========================================================
df = get_bd_df()

# =========================================================
#  UI PRINCIPAL
# =========================================================

st.title("📦 Sistema de Inventario Diario – Restaurante")

st.warning("""
⚠ *Antes de guardar revisa los valores.*  
El botón RESET borra todo y limpia también el carrito interno.
""")

fecha_inv = st.date_input("Fecha de inventario:", value=date.today())
fecha_str = fecha_inv.strftime("%d-%m-%Y")

st.markdown("---")

# =========================================================
#  FILTROS
# =========================================================

areas = sorted([a for a in df["ÁREA"].unique() if a.upper() != "GASTO"])
area = st.selectbox("Área:", areas)

df_area = df[df["ÁREA"] == area]

categorias = sorted(df_area["CATEGORIA"].unique())
categoria = st.selectbox("Categoría:", categorias)

df_cat = df_area[df_area["CATEGORIA"] == categoria]

subfams = sorted(df_cat["SUB FAMILIA"].unique())
subfam = st.selectbox("Sub Familia:", ["TODOS"] + subfams)

df_sf = df_cat if subfam == "TODOS" else df_cat[df_cat["SUB FAMILIA"] == subfam]

productos = df_sf["PRODUCTO GENÉRICO"].tolist()

# =========================================================
#  CREAR TABLA BASE CON CARRITO
# =========================================================

tabla = []
for prod in productos:
    key = (area, prod.upper())
    carrito_vals = st.session_state["carrito"].get(key, {})

    tabla.append({
        "PRODUCTO": prod,
        "UNIDAD": df_sf[df_sf["PRODUCTO GENÉRICO"] == prod]["UNIDAD RECETA"].values[0],
        "MEDIDA": df_sf[df_sf["PRODUCTO GENÉRICO"] == prod]["CANTIDAD DE UNIDAD DE MEDIDA"].values[0],
        "CERRADO": carrito_vals.get("CERRADO", 0.0),
        "ABIERTO(PESO)": carrito_vals.get("ABIERTO(PESO)", 0.0),
        "BOTELLAS_ABIERTAS": carrito_vals.get("BOTELLAS_ABIERTAS", 0.0) if area.upper() == "BARRA" else 0.0
    })

tabla_df = pd.DataFrame(tabla)

editable_cols = ["CERRADO", "ABIERTO(PESO)"]
if area.upper() == "BARRA":
    editable_cols.append("BOTELLAS_ABIERTAS")

tabla_editada = st.data_editor(
    tabla_df,
    use_container_width=True,
    disabled=[c for c in tabla_df.columns if c not in editable_cols],
    key="tabla_inventario"
)

# =========================================================
#  ACTUALIZAR CARRITO
# =========================================================
for _, row in tabla_editada.iterrows():
    key = (area, row["PRODUCTO"].upper())
    st.session_state["carrito"][key] = {
        "CERRADO": float(row["CERRADO"]),
        "ABIERTO(PESO)": float(row["ABIERTO(PESO)"]),
    }
    if "BOTELLAS_ABIERTAS" in row:
        st.session_state["carrito"][key]["BOTELLAS_ABIERTAS"] = float(row["BOTELLAS_ABIERTAS"])


# =========================================================
#  VISTA PREVIA
# =========================================================

st.subheader("Vista previa")

merge_cols = ["PRODUCTO GENÉRICO", "PRECIO NETO", "COSTO X UNIDAD"]
df_merge = df_sf[merge_cols].rename(columns={"PRODUCTO GENÉRICO": "PRODUCTO"})

previo = tabla_editada.merge(df_merge, on="PRODUCTO", how="left")
previo["VALOR INVENTARIO (PREVIO)"] = (
    previo["PRECIO NETO"] * previo["CERRADO"]
    + previo["COSTO X UNIDAD"] * previo["ABIERTO(PESO)"]
)

filtro = (
    (previo["CERRADO"] != 0) |
    (previo["ABIERTO(PESO)"] != 0) |
    ((area.upper() == "BARRA") & (previo.get("BOTELLAS_ABIERTAS", 0) != 0))
)

previo_filtrado = previo[filtro]

cols_prev = ["PRODUCTO", "CERRADO", "ABIERTO(PESO)"]
if area.upper() == "BARRA":
    cols_prev.append("BOTELLAS_ABIERTAS")
cols_prev.append("VALOR INVENTARIO (PREVIO)")

st.dataframe(previo_filtrado[cols_prev], use_container_width=True)


# =========================================================
#  PREPARAR HOJA DESTINO
# =========================================================

ws_dest = get_dest_sheet(area)
header_map = get_header_map(ws_dest)

col_prod = header_map["PRODUCTO GENÉRICO"]
col_cerrado = header_map.get("CANTIDAD CERRADO")
col_abierto = header_map.get("CANTIDAD ABIERTO (PESO)")
col_botellas = header_map.get("CANTIDAD BOTELLAS ABIERTAS")
col_fecha = header_map.get("FECHA")
col_valor = header_map.get("VALOR INVENTARIO")

prod_row_map = get_product_row_map(ws_dest, col_prod)


# =========================================================
#  GUARDAR INVENTARIO
# =========================================================

def guardar_inventario():
    updates = []

    for _, row in tabla_editada.iterrows():
        prod = row["PRODUCTO"].upper()
        if prod not in prod_row_map:
            continue

        r = prod_row_map[prod]

        if col_cerrado:
            letra = colnum_to_colletter(col_cerrado)
            updates.append({"range": f"{letra}{r}", "values": [[row["CERRADO"]]]})

        if col_abierto:
            letra = colnum_to_colletter(col_abierto)
            updates.append({"range": f"{letra}{r}", "values": [[row["ABIERTO(PESO)"]]]})

        if col_botellas and area.upper() == "BARRA":
            letra = colnum_to_colletter(col_botellas)
            updates.append({"range": f"{letra}{r}", "values": [[row["BOTELLAS_ABIERTAS"]]]})

        if col_fecha:
            letra = colnum_to_colletter(col_fecha)
            updates.append({"range": f"{letra}{r}", "values": [[fecha_str]]})

    if updates:
        ws_dest.batch_update(updates)

    st.success("Inventario guardado en Google Sheets.")


# =========================================================
#  RESETEAR INVENTARIO
# =========================================================

def reset_inventario():
    updates = []
    productos_col = ws_dest.col_values(col_prod)
    total = len(productos_col)

    for r in range(4, total + 1):
        if col_cerrado:
            updates.append({"range": f"{colnum_to_colletter(col_cerrado)}{r}", "values": [[0]]})
        if col_abierto:
            updates.append({"range": f"{colnum_to_colletter(col_abierto)}{r}", "values": [[0]]})
        if col_botellas:
            updates.append({"range": f"{colnum_to_colletter(col_botellas)}{r}", "values": [[0]]})
        if col_fecha:
            updates.append({"range": f"{colnum_to_colletter(col_fecha)}{r}", "values": [[""]]})

    if updates:
        ws_dest.batch_update(updates)

    st.session_state["carrito"] = {}  # limpiar carrito
    st.success("Inventario reseteado.")


# =========================================================
#  COMENTARIOS EN C3
# =========================================================

st.subheader("Comentario general del inventario")

comentario = st.text_area("Comentario:", key="comentario_texto")

if st.button("💬 Guardar comentario en hoja"):
    try:
        ws_dest.update("C3", [[comentario]])
        st.success("Comentario guardado en C3.")
    except Exception as e:
        st.error(f"Error guardando comentario: {e}")



# =========================================================
#  BOTONES
# =========================================================

c1, c2 = st.columns(2)

with c1:
    if st.button("💾 Guardar inventario"):
        guardar_inventario()

with c2:
    if st.button("🧹 Resetear inventario"):
        reset_inventario()




