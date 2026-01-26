# GUÍA DE USO DE SERVICIOS SYSTEMD PARA APITM

Esta guía explica cómo instalar y usar los servicios systemd para ejecutar APITM en producción sin Docker.

---

## 📋 SERVICIOS DISPONIBLES

1. **fastapi.service** - Servidor FastAPI (backend)
2. **celery-worker.service** - Celery Worker (procesamiento asíncrono)
3. **celery-beat.service** - Celery Beat (tareas programadas)
4. **frontend.service** - Frontend (opcional, normalmente se sirve con Nginx)

---

## 🚀 INSTALACIÓN RÁPIDA

### Paso 1: Copiar Archivos de Servicio

```bash
# Copiar todos los servicios a systemd
sudo cp /home/usuario/apitm/service/*.service /etc/systemd/system/

# Dar permisos correctos
sudo chmod 644 /etc/systemd/system/fastapi.service
sudo chmod 644 /etc/systemd/system/celery-worker.service
sudo chmod 644 /etc/systemd/system/celery-beat.service
sudo chmod 644 /etc/systemd/system/frontend.service
```

### Paso 2: Crear Directorios de Logs

```bash
# Crear directorio para logs
sudo mkdir -p /var/log/apitm

# Dar permisos al usuario www-data
sudo chown -R www-data:www-data /var/log/apitm
```

### Paso 3: Ajustar Rutas en los Archivos .service

**⚠️ IMPORTANTE:** Editar cada archivo `.service` y cambiar:
- `/home/usuario/apitm` → Ruta real donde está tu proyecto
- `www-data` → Tu usuario (si no usas www-data)

```bash
# Editar servicios
sudo nano /etc/systemd/system/fastapi.service
sudo nano /etc/systemd/system/celery-worker.service
sudo nano /etc/systemd/system/celery-beat.service
sudo nano /etc/systemd/system/frontend.service
```

### Paso 4: Recargar systemd

```bash
sudo systemctl daemon-reload
```

---

## ⚙️ CONFIGURACIÓN DETALLADA

### Usuario y Permisos

Los servicios están configurados para ejecutarse como `www-data`. Si usas otro usuario:

```bash
# Cambiar en cada archivo .service:
User=tu_usuario
Group=tu_usuario

# Dar permisos al directorio del proyecto
sudo chown -R tu_usuario:tu_usuario /home/usuario/apitm
```

### Variables de Entorno

Los servicios cargan variables desde `.env`:

```bash
# Asegurar que existe el archivo .env
ls -la /home/usuario/apitm/microservices/transfermovil/.env

# Debe contener:
# DATABASE_URL, SECRET_KEY, REDIS_URL, etc.
```

### Python y Dependencias

Si usas un entorno virtual:

```bash
# Editar ExecStart en cada servicio:
ExecStart=/home/usuario/apitm/venv/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --workers 4

# O instalar dependencias globalmente (no recomendado)
sudo pip3 install -r /home/usuario/apitm/microservices/transfermovil/requirements.txt
```

---

## 🎮 COMANDOS DE CONTROL

### Iniciar Servicios

```bash
# Iniciar todos los servicios
sudo systemctl start fastapi
sudo systemctl start celery-worker
sudo systemctl start celery-beat
sudo systemctl start frontend  # Opcional

# O iniciar todos a la vez
sudo systemctl start fastapi celery-worker celery-beat
```

### Detener Servicios

```bash
# Detener servicios individuales
sudo systemctl stop fastapi
sudo systemctl stop celery-worker
sudo systemctl stop celery-beat

# Detener todos
sudo systemctl stop fastapi celery-worker celery-beat frontend
```

### Reiniciar Servicios

```bash
# Reiniciar después de cambios en el código
sudo systemctl restart fastapi
sudo systemctl restart celery-worker
sudo systemctl restart celery-beat
```

### Ver Estado

```bash
# Ver estado de un servicio
sudo systemctl status fastapi

# Ver estado de todos
sudo systemctl status fastapi celery-worker celery-beat
```

### Habilitar Inicio Automático

```bash
# Habilitar servicios para que inicien con el sistema
sudo systemctl enable fastapi
sudo systemctl enable celery-worker
sudo systemctl enable celery-beat

# Deshabilitar inicio automático
sudo systemctl disable fastapi
```

---

## 📊 MONITOREO Y LOGS

### Ver Logs en Tiempo Real

```bash
# Logs de FastAPI
sudo tail -f /var/log/apitm/fastapi.log
sudo tail -f /var/log/apitm/fastapi-error.log

# Logs de Celery Worker
sudo tail -f /var/log/apitm/celery-worker.log

# Logs de Celery Beat
sudo tail -f /var/log/apitm/celery-beat.log

# Logs del sistema (systemd journal)
sudo journalctl -u fastapi -f
sudo journalctl -u celery-worker -f
```

### Ver Logs Históricos

```bash
# Últimas 100 líneas
sudo journalctl -u fastapi -n 100

# Logs de hoy
sudo journalctl -u fastapi --since today

# Logs con fecha específica
sudo journalctl -u fastapi --since "2026-01-14 10:00:00"
```

### Limpiar Logs Antiguos

```bash
# Rotar logs manualmente
sudo logrotate -f /etc/logrotate.d/apitm

# Configurar rotación automática
sudo nano /etc/logrotate.d/apitm
```

Contenido de `/etc/logrotate.d/apitm`:

```
/var/log/apitm/*.log {
    daily
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 www-data www-data
    sharedscripts
    postrotate
        systemctl reload fastapi celery-worker celery-beat > /dev/null 2>&1 || true
    endscript
}
```

---

## 🔧 TROUBLESHOOTING

### Servicio no Inicia

```bash
# Ver detalles del error
sudo journalctl -u fastapi -xe

# Verificar sintaxis del archivo
sudo systemd-analyze verify fastapi.service

# Verificar que el directorio existe
ls -la /home/usuario/apitm/microservices/transfermovil

# Verificar permisos
sudo -u www-data ls /home/usuario/apitm/microservices/transfermovil
```

### Error de Permisos

```bash
# Dar permisos al usuario
sudo chown -R www-data:www-data /home/usuario/apitm
sudo chmod -R 755 /home/usuario/apitm

# Verificar que www-data puede escribir logs
sudo -u www-data touch /var/log/apitm/test.log
```

### Servicio se Detiene Constantemente

```bash
# Ver por qué falla
sudo journalctl -u fastapi -n 50

# Verificar que Redis y PostgreSQL están corriendo
sudo systemctl status redis
sudo systemctl status postgresql

# Verificar variables de entorno
sudo -u www-data cat /home/usuario/apitm/microservices/transfermovil/.env
```

### Cambiar Puerto de FastAPI

Editar `/etc/systemd/system/fastapi.service`:

```ini
# Cambiar --port 8001 por el puerto deseado
ExecStart=/usr/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

Luego:

```bash
sudo systemctl daemon-reload
sudo systemctl restart fastapi
```

---

## 🔄 ACTUALIZAR CÓDIGO

### Proceso de Actualización

```bash
# 1. Detener servicios
sudo systemctl stop fastapi celery-worker celery-beat

# 2. Actualizar código (Git o rsync)
cd /home/usuario/apitm
git pull origin main

# 3. Instalar dependencias (si hay cambios)
pip3 install -r microservices/transfermovil/requirements.txt

# 4. Ejecutar migraciones (si hay cambios en BD)
cd microservices/transfermovil
alembic upgrade head

# 5. Reconstruir frontend
cd /home/usuario/apitm/frontend
npm install
npm run build

# 6. Reiniciar servicios
sudo systemctl start fastapi celery-worker celery-beat
```

### Script de Actualización Automática

Crear `/home/usuario/apitm/update.sh`:

```bash
#!/bin/bash
set -e

echo "Deteniendo servicios..."
sudo systemctl stop fastapi celery-worker celery-beat

echo "Actualizando código..."
git pull origin main

echo "Instalando dependencias..."
cd microservices/transfermovil
pip3 install -r requirements.txt

echo "Ejecutando migraciones..."
alembic upgrade head

echo "Reconstruyendo frontend..."
cd ../../frontend
npm install
npm run build

echo "Reiniciando servicios..."
sudo systemctl start fastapi celery-worker celery-beat

echo "✓ Actualización completada"
```

---

## 📈 OPTIMIZACIÓN

### Aumentar Workers de Celery

```bash
# Editar celery-worker.service
sudo nano /etc/systemd/system/celery-worker.service

# Cambiar --concurrency=4 por el número deseado
ExecStart=/usr/bin/python3 -m celery -A app.celery_app.celery_app worker --loglevel=info --concurrency=8
```

### Aumentar Workers de Uvicorn

```bash
# Editar fastapi.service
sudo nano /etc/systemd/system/fastapi.service

# Cambiar --workers 4 por el número deseado (recomendado: 2 x CPU cores)
ExecStart=/usr/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8001 --workers 8
```

### Límites de Recursos

Editar cualquier servicio:

```ini
[Service]
# Límite de archivos abiertos
LimitNOFILE=65536

# Límite de memoria (opcional)
MemoryLimit=2G

# Límite de CPU (opcional, 200% = 2 cores)
CPUQuota=200%
```

---

## ✅ CHECKLIST DE INSTALACIÓN

- [ ] Archivos .service copiados a `/etc/systemd/system/`
- [ ] Rutas ajustadas en los archivos .service
- [ ] Usuario y grupo configurados correctamente
- [ ] Directorio de logs creado (`/var/log/apitm/`)
- [ ] Archivo `.env` existe con todas las variables
- [ ] Redis y PostgreSQL instalados y corriendo
- [ ] Python y dependencias instaladas
- [ ] `systemctl daemon-reload` ejecutado
- [ ] Servicios iniciados correctamente
- [ ] Servicios habilitados para inicio automático
- [ ] Logs funcionando sin errores
- [ ] Nginx configurado para proxy reverso

---

## 📝 NOTAS IMPORTANTES

1. **Frontend Service es Opcional**: Normalmente el frontend se construye una vez (`npm run build`) y Nginx sirve los archivos estáticos directamente. El servicio `frontend.service` es útil solo si quieres reconstruir automáticamente.

2. **Usar Entorno Virtual**: Es recomendable usar un entorno virtual de Python en lugar de instalar dependencias globalmente.

3. **Seguridad**: No ejecutar servicios como `root`. Usar un usuario dedicado como `www-data` o crear uno específico.

4. **Backups**: Antes de actualizar, hacer backup de la base de datos.

---

**Última actualización:** 14 de enero de 2026
