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

# NOMBRE DEL DOCUMENTO (se sigue usando por nombre)
DOC_NAME = "Copia de MACHOTE INV BATANGA DDMMAAAA  ACT25"

# --- CREDENCIALES DESDE secrets.toml ---
service_info = st.secrets["google_service_account"]

credentials = Credentials.from_service_account_info(
    service_info,
    scopes=scope
)

client = gspread.authorize(credentials)


# Abrir el Doc solo una vez usando cache
@st.cache_resource(show_spinner=False)
def get_doc():
    try:
        # Si más adelante quieres usar ID:
        # return client.open_by_key("TU_SPREADSHEET_ID_AQUI")
        return client.open(DOC_NAME)
    except Exception as e:
        st.error(
            f"❌ No se pudo abrir el documento de Google Sheets.\n\n"
            f"Nombre: '{DOC_NAME}'\n\n"
            f"Revisa que:\n"
            f"- El nombre del archivo es correcto.\n"
            f"- El service account tiene acceso (como Editor).\n\n"
            f"Error técnico: {e}"
        )
        st.stop()

doc = get_doc()

BD_TAB = "BD_productos"
INV_CO = "INVENTARIO_COCINA"
INV_SU = "INVENTARIO_SUMINISTROS"
INV_BA = "INVENTARIO_BARRA"


# =========================================================
#  FUNCIONES AUXILIARES
# =========================================================

@st.cache_data(show_spinner=False)
def get_bd_df_cached():
    try:
        ws = doc.worksheet(BD_TAB)
    except Exception as e:
        st.error(
            f"❌ No se pudo abrir la hoja '{BD_TAB}'.\n\n"
            f"Revisa que exista en el archivo y que el service account tenga permisos.\n\n"
            f"Error técnico: {e}"
        )
        st.stop()

    try:
        raw = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")
    except Exception as e:
        st.error(
            f"❌ Error leyendo los datos de la hoja '{BD_TAB}'.\n\n"
            f"Posibles causas:\n"
            f"- Falta de permisos.\n"
            f"- Límite de uso de la API.\n\n"
            f"Error técnico: {e}"
        )
        st.stop()

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

    # Conversión limpia
    for col in numeric_cols:
        if col in df.columns:
            df[col] = (
                df[col]
                .astype(str)
                .str.replace(" ", "")
                .str.replace(",", "")
            )
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    return df


def get_dest_sheet(area: str):
    """
    Devuelve la hoja de inventario destino según el área.
    Hace un manejo robusto de errores por si falla la lectura de worksheets().
    """
    try:
        hojas_list = doc.worksheets()
    except Exception as e:
        st.error(
            "❌ Error al obtener la lista de hojas del documento de Google Sheets.\n\n"
            "Posibles causas:\n"
            "- El service account no tiene permisos sobre el archivo.\n"
            "- Se alcanzó el límite de la API de Google Sheets.\n\n"
            f"Error técnico: {e}"
        )
        st.stop()

    # Diccionario: {"NOMBRE_EN_MAYUS": worksheet}
    hojas = {ws.title.strip().upper(): ws for ws in hojas_list}

    # Normalizar el área seleccionada
    area_norm = area.strip().upper()

    # Mapear el área a la hoja correspondiente
    if area_norm == "COCINA":
        target = INV_CO.upper()
    elif area_norm in ("CONSUMIBLE", "SUMINISTROS"):
        target = INV_SU.upper()
    elif area_norm == "BARRA":
        target = INV_BA.upper()
    else:
        st.error(
            f"❌ El área seleccionada ('{area}') no tiene una hoja asociada.\n\n"
            "Áreas esperadas: COCINA, CONSUMIBLE, BARRA."
        )
        st.stop()

    # Buscar la hoja exacta en mayúsculas
    if target in hojas:
        return hojas[target]

    st.error(
        f"❌ No se encontró la hoja '{target}' en el archivo de Google Sheets.\n\n"
        "Hojas disponibles:\n"
        + ", ".join(hojas.keys())
    )
    st.stop()


def get_header_map(ws):
    """
    Devuelve un dict: NOMBRE_COLUMNA_MAYUS -> índice (1-based)
    Asume que la fila 3 de la hoja de inventario contiene los encabezados.
    Maneja APIError para dar un mensaje entendible.
    """
    try:
        header_row = ws.row_values(3)
    except Exception as e:
        st.error(
            f"❌ Error leyendo la fila 3 de la hoja '{ws.title}'.\n\n"
            "Posibles causas:\n"
            "- La hoja tiene permisos restringidos o rangos protegidos.\n"
            "- El service account no tiene permiso para leer esa hoja.\n"
            "- La API de Google rechazó la petición (rate limit).\n\n"
            f"Error técnico: {e}"
        )
        st.stop()

    if not header_row:
        st.error(
            f"⚠ La fila 3 de la hoja '{ws.title}' está vacía.\n\n"
            "Debes asegurarte de que en la fila 3 estén los encabezados "
            "(PRODUCTO GENÉRICO, CANTIDAD CERRADO, etc.)."
        )
        st.stop()

    header_map = {}
    for idx, name in enumerate(header_row, start=1):
        normalized = str(name).strip().upper()
        if normalized:
            header_map[normalized] = idx

    return header_map


def get_product_row_map(ws, col_idx_producto: int):
    """
    Devuelve dict: PRODUCTO_GENÉRICO_MAYUS -> fila donde está
    Asume datos desde la fila 4 hacia abajo.
    """
    try:
        productos_col = ws.col_values(col_idx_producto)
    except Exception as e:
        st.error(
            f"❌ Error leyendo la columna de productos en la hoja '{ws.title}'.\n\n"
            "Revisa permisos del service account o que la hoja exista correctamente.\n\n"
            f"Error técnico: {e}"
        )
        st.stop()

    mapping = {}
    for row_idx in range(4, len(productos_col) + 1):
        nombre = str(productos_col[row_idx - 1]).strip().upper()
        if nombre:
            mapping[nombre] = row_idx
    return mapping


# =========================================================
#  CARGAR BD (USANDO CACHE)
# =========================================================

df = get_bd_df_cached()

# =========================================================
#  UI PRINCIPAL
# =========================================================

st.title("📦 Sistema de Inventario Diario – Restaurante")

# ===========================
#  ALERTA IMPORTANTE
# ===========================
st.warning(
    """
    ⚠ *Atención al registrar inventario*
    
    - Verifique que las *unidades* (CERRADO y ABIERTO) se ingresen correctamente.  
    - El botón *RESET* borra *TODOS los datos del área seleccionada*, no solo lo filtrado.  
    - Antes de guardar, revise que los valores de *VALOR INVENTARIO (Vista Previa)* sean coherentes.  

    Esta acción no se puede deshacer.
    """,
    icon="⚠"
)

# Control de fecha
fecha_inv = st.date_input("Fecha de inventario:", value=date.today())
fecha_str = fecha_inv.strftime("%d-%m-%Y")

st.markdown("---")

# =======================================
#  FILTROS: ÁREA, CATEGORIA, SUB FAMILIA, PRODUCTO
# =======================================

areas = sorted([a for a in df["ÁREA"].unique() if str(a).upper() != "GASTO"])
area = st.selectbox("Área:", areas)

df_area = df[df["ÁREA"] == area]

categorias = sorted(df_area["CATEGORIA"].unique())
categoria = st.selectbox("Categoría:", categorias)

df_cat = df_area[df_area["CATEGORIA"] == categoria]

# Subfamilia con opción TODOS
subfams = sorted(df_cat["SUB FAMILIA"].unique())
subfam_options = ["TODOS"] + subfams
subfam = st.selectbox("Sub Familia:", subfam_options)

if subfam != "TODOS":
    df_sf = df_cat[df_cat["SUB FAMILIA"] == subfam]
else:
    df_sf = df_cat.copy()

# Productos con opción TODOS
productos_lista = sorted(df_sf["PRODUCTO GENÉRICO"].unique())
prod_options = ["TODOS"] + productos_lista
prod_filtro = st.selectbox("Filtrar por producto específico:", prod_options)

if prod_filtro != "TODOS":
    df_sel = df_sf[df_sf["PRODUCTO GENÉRICO"] == prod_filtro]
else:
    df_sel = df_sf.copy()

if df_sel.empty:
    st.warning("No hay productos bajo esos filtros.")
    st.stop()

st.markdown("---")

# =======================================
#  TABLA EDITABLE
# =======================================

productos = df_sel["PRODUCTO GENÉRICO"].tolist()
n = len(productos)

tabla_base = pd.DataFrame({
    "PRODUCTO": productos,
    "UNIDAD": df_sel["UNIDAD RECETA"].values,
    "MEDIDA": df_sel["CANTIDAD DE UNIDAD DE MEDIDA"].values,
    "CERRADO": [0.0] * n,
    "ABIERTO(PESO)": [0.0] * n,
})

editable_cols = ["CANTIDAD CERRADO", "CANTIDAD ABIERTO (PESO)"]

st.subheader("Listado de productos")

tabla_editada = st.data_editor(
    tabla_base,
    use_container_width=True,
    num_rows="fixed",
    disabled=[c for c in tabla_base.columns if c not in editable_cols],
    key="tabla_inventario",
)

# =======================================
#  VISTA PREVIA DE VALOR INVENTARIO
# =======================================
st.subheader("Vista previa")
merge_cols = [
    "PRODUCTO GENÉRICO",
    "PRECIO NETO",
    "COSTO X UNIDAD",
]
df_merge = df_sel[merge_cols].rename(
    columns={"PRODUCTO GENÉRICO": "PRODUCTO"}
)

previo = tabla_editada.merge(df_merge, on="PRODUCTO", how="left")

previo["VALOR INVENTARIO (PREVIO)"] = (
    previo["PRECIO NETO"] * previo["CANTIDAD CERRADO"]
    + previo["COSTO X UNIDAD"] * previo["CANTIDAD ABIERTO (PESO)"]
)

previo["VALOR INVENTARIO (PREVIO)"] = previo["VALOR INVENTARIO (PREVIO)"].round(2)

st.dataframe(
    previo[[
        "PRODUCTO",
        "CERRADO",
        "ABIERTO (PESO)",
        "VALOR INVENTARIO (PREVIO)",
    ]],
    use_container_width=True,
)

st.info(
    "El VALOR INVENTARIO final lo sigue calculando Google Sheets. "
    "Aquí solo ves una vista previa para revisar antes de guardar."
)

# =======================================
#  PREPARAR HOJA DE INVENTARIO DESTINO
# =======================================

ws_dest = get_dest_sheet(area)
if ws_dest is None:
    st.error(f"No existe hoja de inventario asociada al área '{area}'.")
    st.stop()

header_map = get_header_map(ws_dest)

# Nombres tal como están en las hojas de inventario
prod_col_name = "PRODUCTO GENÉRICO"

if prod_col_name not in header_map:
    st.error(
        "No se encontró la columna 'PRODUCTO GENÉRICO' en la hoja de inventario.\n\n"
        f"Encabezados detectados en la fila 3 de '{ws_dest.title}':\n"
        + ", ".join(header_map.keys())
    )
    st.stop()

col_prod = header_map[prod_col_name]
col_cerrado = header_map.get("CANTIDAD CERRADO")
col_abierto = header_map.get("CANTIDAD ABIERTO (PESO)")
col_valor = header_map.get("VALOR INVENTARIO")   # para reset
col_fecha = header_map.get("FECHA")

prod_row_map = get_product_row_map(ws_dest, col_prod)

if "confirm_reset" not in st.session_state:
    st.session_state["confirm_reset"] = False


# =======================================
#  FUNCIONES: GUARDAR Y RESETEAR
# =======================================

def colnum_to_colletter(n):
    """Convierte número de columna (1=A, 2=B...) a letra."""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(r + ord('A')) + s
    return s


def guardar_inventario():
    filas_actualizadas = 0
    updates = []  # lista de {"range": "", "values": [[]]}

    for _, row in tabla_editada.iterrows():
        prod = str(row["PRODUCTO"]).strip().upper()
        cerrado = row["CANTIDAD CERRADO"]
        abierto = row["CANTIDAD ABIERTO (PESO)"]

        if prod not in prod_row_map:
            continue

        r = prod_row_map[prod]

        # === Actualizar SOLO la celda de CERRADO ===
        if col_cerrado:
            letra = colnum_to_colletter(col_cerrado)
            updates.append({
                "range": f"{letra}{r}",
                "values": [[float(cerrado) if cerrado != "" else 0]]
            })

        # === SOLO la celda de ABIERTO ===
        if col_abierto:
            letra = colnum_to_colletter(col_abierto)
            updates.append({
                "range": f"{letra}{r}",
                "values": [[float(abierto) if abierto != "" else 0]]
            })

        # === SOLO la celda de FECHA ===
        if col_fecha:
            letra = colnum_to_colletter(col_fecha)
            updates.append({
                "range": f"{letra}{r}",
                "values": [[fecha_str]]
            })

        filas_actualizadas += 1

    # Ejecutar todo en una sola llamada
    if updates:
        try:
            ws_dest.batch_update(updates)
        except Exception as e:
            st.error(
                f"❌ Error al guardar los datos en la hoja '{ws_dest.title}'.\n\n"
                "Revisa que la hoja no esté protegida y que el service account tenga permisos.\n\n"
                f"Error técnico: {e}"
            )
            st.stop()

    return filas_actualizadas


def reset_inventario():
    filas_reseteadas = 0
    updates = []

    # Obtener la cantidad total de filas de la hoja
    try:
        productos_col = ws_dest.col_values(col_prod)
    except Exception as e:
        st.error(
            f"❌ Error leyendo la columna de productos al resetear en '{ws_dest.title}'.\n\n"
            f"Error técnico: {e}"
        )
        st.stop()

    total_rows = len(productos_col)

    # Recorremos TODAS las filas válidas (desde la 4)
    for r in range(4, total_rows + 1):

        # === Reset CERRADO ===
        if col_cerrado:
            letra = colnum_to_colletter(col_cerrado)
            updates.append({"range": f"{letra}{r}", "values": [[0]]})

        # === Reset ABIERTO ===
        if col_abierto:
            letra = colnum_to_colletter(col_abierto)
            updates.append({"range": f"{letra}{r}", "values": [[0]]})

        # === Reset FECHA ===
        if col_fecha:
            letra = colnum_to_colletter(col_fecha)
            updates.append({"range": f"{letra}{r}", "values": [[""]]})

        filas_reseteadas += 1

    # Ejecutar en 1 sola llamada
    if updates:
        try:
            ws_dest.batch_update(updates)
        except Exception as e:
            st.error(
                f"❌ Error al resetear datos en la hoja '{ws_dest.title}'.\n\n"
                f"Error técnico: {e}"
            )
            st.stop()

    return filas_reseteadas


# =======================================
#  BOTONES: GUARDAR Y RESET
# =======================================

col_guardar, col_reset = st.columns(2)

with col_guardar:
    if st.button("💾 Guardar inventario (sobrescribir)"):
        n_filas = guardar_inventario()
        st.success(f"✅ Se actualizaron {n_filas} filas en la hoja de inventario.")

with col_reset:
    if st.button("🧹 Resetear cantidades y fecha"):
        st.session_state["confirm_reset"] = True

# Confirmación de reset
if st.session_state.get("confirm_reset", False):
    st.warning(
        "⚠ ¿Seguro que quieres eliminar los datos de "
        "CANTIDAD CERRADO, CANTIDAD ABIERTO (PESO), "
        "VALOR INVENTARIO y FECHA para los productos del área?"
    )

    c1, c2 = st.columns(2)
    with c1:
        if st.button("✅ Sí, borrar"):
            n_reset = reset_inventario()
            st.success(f"Se reseteó la información en {n_reset} filas.")
            st.session_state["confirm_reset"] = False

    with c2:
        if st.button("❌ Cancelar"):
            st.info("Operación cancelada, no se modificó nada.")
            st.session_state["confirm_reset"] = False





