from unicodedata import category

import pandas as pd
import xmlrpc.client
import logging
import datetime
import os

fecha_actual = datetime.datetime.now().strftime('%Y%m%d')

# --- Logs ---
os.makedirs("/logs", exist_ok=True)

update_log = f"/logs/pixie_update_{fecha_actual}.log"
error_log = f"/logs/pixie_error_{fecha_actual}.log"
nuevos_log = f"/logs/pixie_nuevos_{fecha_actual}.log"

logger_general = logging.getLogger("general")
logger_error = logging.getLogger("errores")
logger_nuevos = logging.getLogger("nuevos")

logger_general.setLevel(logging.INFO)
logger_error.setLevel(logging.ERROR)
logger_nuevos.setLevel(logging.INFO)

formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')


def _add_handler_once(logger, handler):
    # Evita duplicar handlers si ejecutas el script más de una vez en el mismo proceso
    if not any(getattr(h, "baseFilename", None) == getattr(handler, "baseFilename", None) for h in logger.handlers):
        logger.addHandler(handler)


fh_general = logging.FileHandler(update_log)
fh_general.setFormatter(formatter)
_add_handler_once(logger_general, fh_general)
_add_handler_once(logger_general, logging.StreamHandler())

fh_error = logging.FileHandler(error_log)
fh_error.setFormatter(formatter)
_add_handler_once(logger_error, fh_error)

fh_nuevos = logging.FileHandler(nuevos_log)
fh_nuevos.setFormatter(formatter)
_add_handler_once(logger_nuevos, fh_nuevos)

# --- CSV ---
csv_path = r"C:\Users\Usuario\Downloads\Telegram Desktop\listas_odoo.csv"
df = pd.read_csv(csv_path, sep=";", engine="python")
logger_general.info("Columnas disponibles en el CSV: %s", list(df.columns))

# --- Odoo XML-RPC ---
ODOO_URL = "http://localhost:8069"
ODOO_DB = "****"
ODOO_USER = "*****"
ODOO_PASSWORD = "*****"

common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common")
uid = common.authenticate(ODOO_DB, ODOO_USER, ODOO_PASSWORD, {})
models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object")


def safe_str(val) -> str:
    return "" if pd.isna(val) else " - " + str(val)


def to_float(val, default=0.0) -> float:
    """
    Convierte valores tipo '1.234,56' o '1234.56' a float, y maneja NaN.
    """
    if pd.isna(val):
        return float(default)
    s = str(val).strip()
    if not s:
        return float(default)
    s = s.replace(".", "").replace(",", ".")  # por si viene con formato ES
    try:
        return float(s)
    except ValueError:
        return float(default)


def build_description(row) -> str:
    base = "" if pd.isna(row.get("Descripcion")) else str(
        row.get("Descripcion"))
    return (
        f"{base}"
        f"{safe_str(row.get('Color'))}"
        f"{safe_str(row.get('Contenido'))}"
        f"{safe_str(row.get('Presentacion'))}"
    ).strip()


def get_or_create_category(name):
    category_ids = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
                                     'product.category', 'search',
                                     [[['name', '=', name]]])
    if category_ids:
        return category_ids[0]
    else:
        return models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
                                 'product.category', 'create',
                                 [{'name': name}])


# --- Procesar cada fila ---
for index, row in df.iterrows():
    product_code = "UNKNOWN"
    try:
        product_code = str(row["ID"]).strip()
        if not product_code:
            raise ValueError("ID (product_code) vacío")

        new_price_cost = to_float(row.get("Costo C/IVA"), default=0.0)
        contado = to_float(row.get("Contado"), default=0.0)
        descripcion = build_description(row) or product_code

        logger_general.info(
            "Procesando #%d: Código=%s, Costo=%s, Contado=%s",
            index + 1, product_code, new_price_cost, contado
        )

        # 1) Buscar variante por default_code en product.product
        product_ids = models.execute_kw(
            ODOO_DB, uid, ODOO_PASSWORD,
            "product.product", "search",
            [[["default_code", "=", product_code]]],
            {"limit": 1}
        )
        category_id = get_or_create_category(row.get("Categoria odoo", ""))
        marca = row.get("Marca", "")
        # Buscar si existe ese atributo en odoo, sino crearlo
        attribute_id = None
        if marca:
            attribute_ids = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
                                              'product.attribute', 'search',
                                              [[['name', '=', 'Brand']]])
            if attribute_ids:
                attribute_id = attribute_ids[0]
            else:
                attribute_id = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
                                                 'product.attribute', 'create',
                                                 [{'name': 'Brand'}])
                logger_general.info(
                    "Atributo 'Brand' creado con ID %s", attribute_id)
                # Buscar o crear el valor del atributo
            value_id = None
            value_ids = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
                                          'product.attribute.value', 'search',
                                          [[['name', '=', marca], ['attribute_id', '=', attribute_id]]])
            if value_ids:
                value_id = value_ids[0]
            else:
                value_id = models.execute_kw(ODOO_DB, uid, ODOO_PASSWORD,
                                             'product.attribute.value', 'create',
                                             [{'name': marca, 'attribute_id': attribute_id}])
                logger_general.info(
                    "Valor de atributo 'Marca' creado: %s (ID %s)", marca, value_id)
        if product_ids:
            # 2) Obtener el template y actualizar ahí (name/list_price/standard_price)
            product_data = models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                "product.product", "read",
                [product_ids, ["product_tmpl_id"]]
            )
            tmpl_id = product_data[0]["product_tmpl_id"][0]

            vals = {"name": descripcion}
            if new_price_cost > 0:
                vals["standard_price"] = new_price_cost
            if contado > 0:
                vals["list_price"] = contado
            vals["categ_id"] = category_id
            if attribute_id:
                vals["attribute_line_ids"] = [(0, 0, {
                    "attribute_id": attribute_id,
                    "value_ids": [(6, 0, [value_id])] if value_id else []
                })]
            models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                "product.template", "write",
                [[tmpl_id], vals]
            )
            logger_general.info(
                "Actualizado %s (template_id=%s) con vals=%s",
                product_code, tmpl_id, vals
            )

        else:
            # 3) No existe: crear product.template (Odoo creará la variante)
            vals_create = {
                "name": descripcion,
                "default_code": product_code,
                "description": descripcion,
                "categ_id": category_id,
                "attribute_line_ids": [(0, 0, {
                    "attribute_id": attribute_id,
                    "value_ids": [(6, 0, [value_id])] if value_id else []
                })] if attribute_id else [],
                # "type": "product",  # producto almacenable; cambia a 'consu' si corresponde
            }
            if new_price_cost > 0:
                vals_create["standard_price"] = new_price_cost
            if contado > 0:
                vals_create["list_price"] = contado

            tmpl_id = models.execute_kw(
                ODOO_DB, uid, ODOO_PASSWORD,
                "product.template", "create",
                [vals_create]
            )
            logger_nuevos.info(
                "Producto creado en Odoo: %s (template_id=%s) vals=%s",
                product_code, tmpl_id, vals_create
            )

    except Exception as e:
        logger_error.error("Error en producto %s: %s",
                           product_code, str(e), exc_info=True)

logger_general.info("Finalizó la ejecución del script.")
