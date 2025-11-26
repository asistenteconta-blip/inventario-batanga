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
        st.error(f"❌ No se pudo abrir el documento de Google Sheets:\n{e}")
        st.stop()

doc = get_doc()

BD_TAB = "BD_productos"
INV_CO = "INVENTARIO_COCINA"
INV_SU = "INVENTARIO_SUMINISTROS"
INV_BA = "INVENTARIO_BARRA"

# Fila donde están los encabezados en las hojas de inventario
HEADER_ROW = 4
FIRST_DATA_ROW = 5  # primera fila con productos

# =========================================================
#   CARRITO GLOBAL (Opción C)
# =========================================================
if "carrito" not in st.session_state:
    st.session_state["carrito"] = {}

if "confirm_reset" not in st.session_state:
    st.session_state["confirm_reset"] = False

# =========================================================
#  FUNCIONES AUXILIARES
# =========================================================

@st.cache_data(show_spinner=False)
def get_bd_df_cached():
    ws = doc.worksheet(BD_TAB)
    raw = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")

    if not raw or len(raw) < 2:
        st.error("❌ La hoja BD_productos está vacía o no tiene datos.")
        st.stop()

    headers = [h.strip() for h in raw[0]]
    df = pd.DataFrame(raw[1:], columns=headers)

    # Normalizar encabezados
    df.columns = df.columns.str.strip().str.upper()

    # Columnas numéricas
    numeric_cols = [
        "PRECIO NETO",
        "CANTIDAD DE UNIDAD DE MEDIDA",
        "COSTO X UNIDAD",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = (
                df[col].astype(str)
                .str.replace(" ", "")
                .str.replace(",", "")
            )
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    return df


def get_dest_sheet(area: str):
    hojas = {ws.title.upper(): ws for ws in doc.worksheets()}
    area_norm = area.strip().upper()

    if area_norm == "COCINA":
        target = INV_CO.upper()
    elif area_norm in ("CONSUMIBLE", "SUMINISTROS"):
        target = INV_SU.upper()
    elif area_norm == "BARRA":
        target = INV_BA.upper()
    else:
        st.error(f"❌ Área inválida: {area}")
        st.stop()

    if target not in hojas:
        st.error(
            f"❌ No se encontró la hoja '{target}' en el archivo.\n\n"
            "Hojas disponibles:\n" + ", ".join(hojas.keys())
        )
        st.stop()

    return hojas[target]


def get_header_map(ws):
    # Ahora los encabezados están en la fila 4
    header_row = ws.row_values(HEADER_ROW)
    if not header_row:
        st.error(
            f"⚠ La fila {HEADER_ROW} de la hoja '{ws.title}' está vacía.\n"
            "Ahí deben estar los encabezados (PRODUCTO GENÉRICO, etc.)."
        )
        st.stop()

    return {
        str(h).strip().upper(): idx
        for idx, h in enumerate(header_row, start=1)
        if str(h).strip()
    }


def get_product_row_map(ws, col_idx_producto: int):
    # Datos empiezan en FIRST_DATA_ROW
    col = ws.col_values(col_idx_producto)
    mapping = {}
    for row_idx in range(FIRST_DATA_ROW, len(col) + 1):
        nombre = str(col[row_idx - 1]).strip().upper()
        if nombre:
            mapping[nombre] = row_idx
    return mapping


def colnum_to_colletter(n: int) -> str:
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(r + ord("A")) + s
    return s

# =========================================================
#  CARGAR BD
# =========================================================

df = get_bd_df_cached()

# =========================================================
#  UI PRINCIPAL
# =========================================================

st.title("📦 Sistema de Inventario Diario – Restaurante")

st.warning(
    """
    ⚠ *Atención al registrar inventario*
    
    - Verifique que las *unidades* se ingresen correctamente.  
    - El botón *RESET* borra TODO el inventario del área (y limpia el carrito y el comentario).  
    - Revise la vista previa antes de guardar.
    """,
    icon="⚠"
)

fecha_inv = st.date_input("Fecha de inventario:", value=date.today())
fecha_str = fecha_inv.strftime("%d-%m-%Y")

st.markdown("---")

# =========================================================
#  FILTROS
# =========================================================

areas = sorted([a for a in df["ÁREA"].unique() if str(a).upper() != "GASTO"])
area = st.selectbox("Área:", areas)

df_area = df[df["ÁREA"] == area]

categorias = sorted(df_area["CATEGORIA"].unique())
categoria = st.selectbox("Categoría:", categorias)

df_cat = df_area[df_area["CATEGORIA"] == categoria]

subfams = sorted(df_cat["SUB FAMILIA"].unique())
subfam_options = ["TODOS"] + subfams
subfam = st.selectbox("Sub Familia:", subfam_options)

if subfam != "TODOS":
    df_sf = df_cat[df_cat["SUB FAMILIA"] == subfam]
else:
    df_sf = df_cat.copy()

# Filtro por producto específico (con opción TODOS)
productos_lista = sorted(df_sf["PRODUCTO GENÉRICO"].unique())
prod_options = ["TODOS"] + productos_lista
prod_filtro = st.selectbox("Filtrar por producto específico:", prod_options)

if prod_filtro != "TODOS":
    df_sel = df_sf[df_sf["PRODUCTO GENÉRICO"] == prod_filtro]
else:
    df_sel = df_sf.copy()

if df_sel.empty:
    st.warning("No hay productos con esos filtros.")
    st.stop()

st.markdown("---")

# =========================================================
#  TABLA EDITABLE CON CARRITO
# =========================================================

productos = df_sel["PRODUCTO GENÉRICO"].tolist()
tabla_rows = []

for prod in productos:
    key = (area, prod.strip().upper())
    carrito_vals = st.session_state["carrito"].get(key, {})

    fila_df = df_sel[df_sel["PRODUCTO GENÉRICO"] == prod]

    unidad = fila_df["UNIDAD RECETA"].values[0]
    medida = fila_df["CANTIDAD DE UNIDAD DE MEDIDA"].values[0]

   # ==========================================================
# Construimos tabla preservando valores previos del carrito
# ==========================================================

tabla_rows.append({
    "PRODUCTO": prod,
    "UNIDAD": unidad,
    "MEDIDA": medida,

    # estos valores ya NO vuelven a 0 nunca al filtrar o cambiar categoría
    "CERRADO": st.session_state["carrito"].get((area, prod.upper()), {}).get("CERRADO", float("nan")),
    "ABIERTO(PESO)": st.session_state["carrito"].get((area, prod.upper()), {}).get("ABIERTO(PESO)", float("nan")),
    "BOTELLAS_ABIERTAS": st.session_state["carrito"].get((area, prod.upper()), {}).get("BOTELLAS_ABIERTAS", float("nan")) if area.upper()=="BARRA" else float("nan"),
})



tabla_base = pd.DataFrame(tabla_rows)

editable_cols = ["CERRADO", "ABIERTO(PESO)"]
if area.upper() == "BARRA":
    editable_cols.append("BOTELLAS_ABIERTAS")

st.subheader("Listado de productos")

tabla_editada = st.data_editor(
    tabla_base,
    use_container_width=True,
    num_rows="fixed",
    disabled=[c for c in tabla_base.columns if c not in editable_cols],
    key="tabla_inventario",
)

# ==============================
# ==============================
#  Actualizar carrito sin perder datos al cambiar categoría
# ==============================
for _, row in tabla_editada.iterrows():
    key = (area, str(row["PRODUCTO"]).strip().upper())

    current = st.session_state["carrito"].get(key, {})

    st.session_state["carrito"][key] = {
        "CERRADO": float(row["CERRADO"]) if row["CERRADO"] not in ("", None) else current.get("CERRADO", 0.0),
        "ABIERTO(PESO)": float(row["ABIERTO(PESO)"]) if row["ABIERTO(PESO)"] not in ("", None) else current.get("ABIERTO(PESO)", 0.0),
    }

    if area.upper() == "BARRA":
        st.session_state["carrito"][key]["BOTELLAS_ABIERTAS"] = (
            float(row["BOTELLAS_ABIERTAS"]) if row["BOTELLAS_ABIERTAS"] not in ("", None)
            else current.get("BOTELLAS_ABIERTAS", 0.0)
        )



# =========================================================
#  VISTA PREVIA
# =========================================================

st.subheader("Vista previa")

merge_cols = ["PRODUCTO GENÉRICO", "PRECIO NETO", "COSTO X UNIDAD"]
df_merge = df_sel[merge_cols].rename(columns={"PRODUCTO GENÉRICO": "PRODUCTO"})

previo = tabla_editada.merge(df_merge, on="PRODUCTO", how="left")

previo["VALOR INVENTARIO (PREVIO)"] = (
    previo["PRECIO NETO"] * previo["CERRADO"]
    + previo["COSTO X UNIDAD"] * previo["ABIERTO(PESO)"]
)
previo["VALOR INVENTARIO (PREVIO)"] = previo["VALOR INVENTARIO (PREVIO)"].round(2)

# Solo mostrar productos con algún valor != 0
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

st.info(
    "El VALOR INVENTARIO final lo sigue calculando Google Sheets. "
    "Aquí solo ves una vista previa para revisar antes de guardar."
)

# =========================================================
#  PREPARAR HOJA DESTINO
# =========================================================

ws_dest = get_dest_sheet(area)
header_map = get_header_map(ws_dest)

prod_col_name = "PRODUCTO GENÉRICO"
if prod_col_name not in header_map:
    st.error(
        "No se encontró la columna 'PRODUCTO GENÉRICO' en la hoja de inventario.\n\n"
        f"Encabezados detectados en la fila {HEADER_ROW} de '{ws_dest.title}':\n"
        + ", ".join(header_map.keys())
    )
    st.stop()

col_prod = header_map[prod_col_name]
col_cerrado = header_map.get("CANTIDAD CERRADO")
col_abierto = header_map.get("CANTIDAD ABIERTO (PESO)")
col_botellas = header_map.get("CANTIDAD BOTELLAS ABIERTAS")
col_valor = header_map.get("VALOR INVENTARIO")
col_fecha = header_map.get("FECHA")

prod_row_map = get_product_row_map(ws_dest, col_prod)

# =========================================================
#  FUNCIONES GUARDAR / RESET
# =========================================================

def guardar_inventario():
    updates = []
    filas_actualizadas = 0

    for _, row in tabla_editada.iterrows():
        prod = str(row["PRODUCTO"]).strip().upper()
        if prod not in prod_row_map:
            continue

        r = prod_row_map[prod]

        if col_cerrado:
            letra = colnum_to_colletter(col_cerrado)
            updates.append(
                {"range": f"{letra}{r}", "values": [[float(row["CERRADO"])]]}
            )

        if col_abierto:
            letra = colnum_to_colletter(col_abierto)
            updates.append(
                {"range": f"{letra}{r}", "values": [[float(row["ABIERTO(PESO)"])]]}
            )

        if col_botellas and area.upper() == "BARRA":
            letra = colnum_to_colletter(col_botellas)
            updates.append(
                {"range": f"{letra}{r}", "values": [[float(row["BOTELLAS_ABIERTAS"])]]}
            )

        if col_fecha:
            letra = colnum_to_colletter(col_fecha)
            updates.append(
                {"range": f"{letra}{r}", "values": [[fecha_str]]}
            )

        filas_actualizadas += 1

    if updates:
        ws_dest.batch_update(updates)

    return filas_actualizadas


def reset_inventario():
    updates = []

    # Reset de todas las filas de productos del área
    productos_col = ws_dest.col_values(col_prod)
    total_rows = len(productos_col)

    for r in range(FIRST_DATA_ROW, total_rows + 1):
        if col_cerrado:
            letra = colnum_to_colletter(col_cerrado)
            updates.append({"range": f"{letra}{r}", "values": [[0]]})
        if col_abierto:
            letra = colnum_to_colletter(col_abierto)
            updates.append({"range": f"{letra}{r}", "values": [[0]]})
        if col_botellas:
            letra = colnum_to_colletter(col_botellas)
            updates.append({"range": f"{letra}{r}", "values": [[0]]})
        if col_valor:
            letra = colnum_to_colletter(col_valor)
            updates.append({"range": f"{letra}{r}", "values": [[0]]})
        if col_fecha:
            letra = colnum_to_colletter(col_fecha)
            updates.append({"range": f"{letra}{r}", "values": [[""]]})

    # Borrar comentario en C3
    updates.append({"range": "C3", "values": [[""]]})

    if updates:
        ws_dest.batch_update(updates)

   # Limpiar carrito + comentario correctamente
st.session_state["carrito"] = {}
st.session_state.pop("comentario_texto", None)


# =========================================================
#  COMENTARIO EN C3
# =========================================================

st.subheader("Comentario general del inventario")

comentario = st.text_area(
    "Comentario:",
    key="comentario_texto",
    placeholder="Escribe aquí un comentario general del inventario..."
)

if st.button("💬 Guardar comentario en hoja"):
    try:
        ws_dest.update("C3", [[comentario]])
        st.success("Comentario guardado en C3.")
    except Exception as e:
        st.error(f"Error guardando comentario: {e}")

# =========================================================
#  BOTONES GUARDAR / RESET (CON DOBLE CONFIRMACIÓN)
# =========================================================

col_guardar, col_reset = st.columns(2)

with col_guardar:
    if st.button("💾 Guardar inventario (sobrescribir)"):
        n_filas = guardar_inventario()
        st.success(f"✅ Se actualizaron {n_filas} filas en la hoja de inventario.")

with col_reset:
    if st.button("🧹 Resetear inventario del área"):
        st.session_state["confirm_reset"] = True

if st.session_state.get("confirm_reset", False):
    st.warning(
        "⚠ ¿Seguro que quieres eliminar los datos de "
        "CANTIDAD CERRADO, CANTIDAD ABIERTO (PESO), "
        "CANTIDAD BOTELLAS ABIERTAS, VALOR INVENTARIO y FECHA "
        "para TODOS los productos del área, y borrar el comentario?",
        icon="⚠"
    )

    c1, c2 = st.columns(2)
    with c1:
        if st.button("✅ Sí, borrar TODO"):
            reset_inventario()
            st.success("Inventario y comentario reseteados.")
            st.session_state["confirm_reset"] = False

    with c2:
        if st.button("❌ Cancelar operación"):
            st.info("Operación cancelada. No se modificó nada.")
            st.session_state["confirm_reset"] = False




