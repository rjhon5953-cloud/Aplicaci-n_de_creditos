import datetime
import sqlite3
from functools import wraps
from flask import Flask, jsonify, request
import jwt

app = Flask(__name__)
JWT_SECRET = "AVANTA_SECRET_KEY_2026"


# === CONFIGURACIÓN Y CREACIÓN DE LA BASE DE DATOS ===
def inicializar_bd():
    conn = sqlite3.connect("avanta_pagos.db")
    cursor = conn.cursor()

    # 1. Tabla de Usuarios
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            rol TEXT DEFAULT 'gestor',
            activo INTEGER DEFAULT 1
        )
    """
    )

    # 2. Tabla de Clientes
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            identificacion TEXT UNIQUE NOT NULL,
            estado_credito TEXT DEFAULT 'activo',
            cupo_disponible REAL DEFAULT 0.00
        )
    """
    )

    # 3. Tabla de Pagos
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS pagos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cliente_id INTEGER NOT NULL,
            monto REAL NOT NULL,
            estado TEXT DEFAULT 'pendiente',
            fecha_pago TEXT NOT NULL,
            usuario_id INTEGER NOT NULL,
            FOREIGN KEY(cliente_id) REFERENCES clientes(id),
            FOREIGN KEY(usuario_id) REFERENCES usuarios(id)
        )
    """
    )

    # 4. Tabla de Reversiones
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS historial_reversiones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pago_id INTEGER NOT NULL,
            usuario_id INTEGER NOT NULL,
            motivo TEXT NOT NULL,
            fecha_reversion TEXT NOT NULL,
            FOREIGN KEY(pago_id) REFERENCES pagos(id),
            FOREIGN KEY(usuario_id) REFERENCES usuarios(id)
        )
    """
    )

    # Insertar datos de prueba iniciales (Solo si la tabla está vacía)
    cursor.execute("SELECT COUNT(*) FROM usuarios")
    if cursor.fetchone()[0] == 0:
        cursor.execute(
            "INSERT INTO usuarios (username, password, rol) VALUES ('admin', '1234', 'admin')"
        )
        cursor.execute(
            "INSERT INTO clientes (nombre, identificacion, estado_credito, cupo_disponible) VALUES ('Juan Perez', '0999999999', 'liquidado', 0.00)"
        )
        cursor.execute(
            "INSERT INTO clientes (nombre, identificacion, estado_credito, cupo_disponible) VALUES ('Maria Lopez', '0888888888', 'activo', 150.00)"
        )

        # Insertar un pago completado con la fecha de hoy para el panel
        fecha_hoy = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "INSERT INTO pagos (cliente_id, monto, estado, fecha_pago, usuario_id) VALUES (2, 45.50, 'completado', ?, 1)",
            (fecha_hoy,),
        )

    conn.commit()
    conn.close()


inicializar_bd()


# === MIDDLEWARE DE AUTENTICACIÓN JWT ===
def verificar_jwt(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if "Authorization" in request.headers:
            auth_header = request.headers["Authorization"].split(" ")
            if len(auth_header) == 2:
                token = auth_header[1]

        if not token:
            return (
                jsonify(
                    {
                        "success": False,
                        "message": "Acceso denegado. Token no proporcionado.",
                    }
                ),
                401,
            )

        try:
            data = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
            request.user = data  # Inyectamos los datos decodificados en la petición
        except Exception:
            return (
                jsonify({"success": False, "message": "Token inválido o expirado."}),
                403,
            )

        return f(*args, **kwargs)

    return decorated


# === ENDPOINTS DE LA API ===


# 1. Login público
@app.route("/api/login", methods=["POST"])
def login():
    datos = request.get_json() or {}
    username = datos.get("username")
    password = datos.get("password")

    if not username or not password:
        return (
            jsonify({"success": False, "message": "Campos requeridos vacíos."}),
            400,
        )

    conn = sqlite3.connect("avanta_pagos.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM usuarios WHERE username = ? AND activo = 1", (username,)
    )
    usuario = cursor.fetchone()
    conn.close()

    if not usuario or usuario["password"] != str(password):
        return (
            jsonify({"success": False, "message": "Credenciales incorrectas."}),
            401,
        )

    # Generar Token válido por 8 horas
    token = jwt.encode(
        {
            "id": usuario["id"],
            "username": usuario["username"],
            "rol": usuario["rol"],
            "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=8),
        },
        JWT_SECRET,
        algorithm="HS256",
    )

    return jsonify(
        {
            "success": True,
            "message": "Autenticación exitosa.",
            "token": token,
            "usuario": {"username": usuario["username"], "rol": usuario["rol"]},
        }
    )


# 2. Panel de Cobros del Día (/menu/pagos_hoy)
@app.route("/menu/pagos_hoy", methods=["GET"])
@verificar_jwt
def get_pagos_hoy():
    conn = sqlite3.connect("avanta_pagos.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    fecha_hoy_busqueda = datetime.datetime.now().strftime("%Y-%m-%d")

    query = """
        SELECT p.id, p.monto, p.estado, p.fecha_pago,
               c.id AS cliente_id, c.nombre AS cliente_nombre,
               u.username AS registrado_por
        FROM pagos p
        INNER JOIN clientes c ON p.cliente_id = c.id
        INNER JOIN usuarios u ON p.usuario_id = u.id
        WHERE date(p.fecha_pago) = ?
    """
    cursor.execute(query, (fecha_hoy_busqueda,))
    rows = cursor.fetchall()
    conn.close()

    items = [dict(row) for row in rows]
    total_recaudado = sum(
        float(p["monto"]) for p in items if p["estado"] == "completado"
    )

    return jsonify(
        {
            "success": True,
            "data": {
                "fecha": fecha_hoy_busqueda,
                "total_recaudado": total_recaudado,
                "items": items,
            }
        }
    )


# 3. Reversiones de Gestión (/api/revertir_gestion)
@app.route("/api/revertir_gestion", methods=["POST"])
@verificar_jwt
def revertir_gestion():
    datos = request.get_json() or {}
    pago_id = datos.get("pago_id")
    motivo = datos.get("motivo", "Corrección operativa estándar")
    usuario_autoriza = request.user["id"]

    if not pago_id:
        return (
            jsonify(
                {"success": False, "message": "El parámetro pago_id es mandatorio."}
            ),
            400,
        )

    conn = sqlite3.connect("avanta_pagos.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT estado FROM pagos WHERE id = ?", (pago_id,))
    pago = cursor.fetchone()

    if not pago:
        conn.close()
        return jsonify({"success": False, "message": "El cobro no existe."}), 442

    if pago["estado"] != "completado":
        conn.close()
        return (
            jsonify(
                {
                    "success": False,
                    "message": f"No se puede revertir un cobro en estado: {pago['estado']}",
                }
            ),
            400,
        )

    try:
        # Actualizar estado del pago
        cursor.execute(
            "UPDATE pagos SET estado = 'revertido' WHERE id = ?", (pago_id,)
        )

        # Registrar auditoría
        fecha_reversion = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "INSERT INTO historial_reversiones (pago_id, usuario_id, motivo, fecha_reversion) VALUES (?, ?, ?, ?)",
            (pago_id, usuario_autoriza, motivo, fecha_reversion),
        )

        conn.commit()
        return jsonify(
            {
                "success": True,
                "message": f"El cobro #{pago_id} ha sido revertido exitosamente.",
            }
        )
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        conn.close()


# 4. Reactivación de Créditos (/api/clientes/reactivar)
@app.route("/api/clientes/reactivar", methods=["PUT"])
@verificar_jwt
def reactivar_credito():
    if request.user["rol"] != "admin":
        return (
            jsonify(
                {
                    "success": False,
                    "message": "Permisos insuficientes. Requiere rol de Administrador.",
                }
            ),
            403,
        )

    datos = request.get_json() or {}
    cliente_id = datos.get("cliente_id")
    nuevo_monto_limite = datos.get("nuevo_monto_limite")

    if cliente_id is None or nuevo_monto_limite is None or nuevo_monto_limite < 0:
        return (
            jsonify(
                {"success": False, "message": "Datos de entrada inválidos."}
            ),
            400,
        )

    conn = sqlite3.connect("avanta_pagos.db")
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE clientes SET estado_credito = 'activo', cupo_disponible = ? WHERE id = ? AND estado_credito = 'liquidado'",
        (nuevo_monto_limite, cliente_id),
    )
    filas_afectadas = cursor.rowcount
    conn.commit()
    conn.close()

    if filas_afectadas == 0:
        return (
            jsonify(
                {
                    "success": False,
                    "message": "No se modificó el registro. Verifique que el cliente esté en estado 'liquidado'.",
                }
            ),
           422,
        )

    return jsonify(
        {
            "success": True,
            "message": f"Crédito reactivado para el cliente #{cliente_id}. Cupo asignado: ${nuevo_monto_limite}",
        }
    )


if __name__ == "__main__":
    # Servidor de Avanta Pagos configurado en el puerto 8080
    app.run(host="0.0.0.0", port=8080, debug=True)
