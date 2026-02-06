
import requests
from uuid import uuid4
from app.core.config import settings
import os
import logging
logger = logging.getLogger(__name__)


class ImageHelper:

    image_dir: str = settings.image_dir
    fast_api_host: str = settings.fast_api_host
    allowed_mime_types = ("image/jpeg", "image/png", "image/webp")

    def __init__(self, image_dir: str = None,
                 fast_api_host: str = None,
                 allowed_mime_types: tuple = None) -> None:
        if image_dir:
            self.image_dir = image_dir
        if fast_api_host:
            self.fast_api_host = fast_api_host
        if allowed_mime_types:
            self.allowed_mime_types = allowed_mime_types

    def download_and_save_image(self, url: str) -> dict:

        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "image/*",
        }

        with requests.get(url, headers=headers, stream=True, timeout=60, cookies={"session_id": "abc123"}) as r:
            r.raise_for_status()
            content_type = r.headers.get("Content-Type", "")
            if content_type not in self.allowed_mime_types:
                logger.warning(f"MIME inválido: {content_type}")
                raise ValueError(f"MIME inválido: {content_type}")

            extension = {
                "image/jpeg": "jpg",
                "image/png": "png",
                "image/webp": "webp",
            }[content_type]

            filename = f"{uuid4().hex}.{extension}"
            file_path = os.path.join(self.image_dir, filename)
            with open(file_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

        return f"{self.fast_api_host}/images/products/{filename}", file_path

    def remove_local_image(self, file_paths: list) -> None:
        """Elimina una imagen localmente después de subirla a WooCommerce"""
        try:
            for file_path in file_paths:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logger.info(f"Imagen eliminada: {file_path}")
            else:
                logger.warning(
                    f"Archivo no encontrado para eliminación: {file_path}")
        except Exception as e:
            logger.error(f"Error eliminando imagen local: {e}", exc_info=True)

    def extract_image_urls(odoo_product_data):
        image_urls = []
        if "image_1920" in odoo_product_data and odoo_product_data["image_1920"]:
            image_urls.append(odoo_product_data["image_1920"])
        if "image_1024" in odoo_product_data and odoo_product_data["image_1024"]:
            image_urls.append(odoo_product_data["image_1024"])
        if "image_512" in odoo_product_data and odoo_product_data["image_512"]:
            image_urls.append(odoo_product_data["image_512"])
        if "image_256" in odoo_product_data and odoo_product_data["image_256"]:
            image_urls.append(odoo_product_data["image_256"])
        if "image_128" in odoo_product_data and odoo_product_data["image_128"]:
            image_urls.append(odoo_product_data["image_128"])
        return image_urls
