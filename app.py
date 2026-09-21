import os
import sqlite3
import urllib.parse
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta
from flask import Flask, redirect, render_template_string, request, send_file

app = Flask(__name__)

# En Render los datos persisten si se usa la carpeta /tmp o un disco montado, 
# pero para uso general lo guardamos localmente en el directorio de la app.
DB_NAME = "creditos.db"


# =====================================================
# BASE DE DATOS (SQLITE)
# =====================================================
def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS clientes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                telefono TEXT,
                identificacion TEXT,
                monto REAL NOT NULL,
                interes_porcentaje REAL NOT NULL DEFAULT 20,
                monto_total REAL NOT NULL DEFAULT 0,
                cuotas INTEGER NOT NULL,
                frecuencia TEXT NOT NULL,
                valor_cuota REAL NOT NULL,
                fecha_inicio TEXT NOT NULL
            )
        """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pagos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cliente_id INTEGER NOT NULL,
                numero INTEGER NOT NULL,
                fecha TEXT NOT NULL,
                valor REAL NOT NULL,
                pagado INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (cliente_id) REFERENCES clientes (id) ON DELETE CASCADE
            )
        """
        )

        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(clientes)")
        columnas = [col[1] for col in cursor.fetchall()]

        if "interes_porcentaje" not in columnas:
            cursor.execute(
                "ALTER TABLE clientes ADD COLUMN interes_porcentaje REAL NOT NULL DEFAULT 20"
            )
        if "monto_total" not in columnas:
            cursor.execute(
                "ALTER TABLE clientes ADD COLUMN monto_total REAL NOT NULL DEFAULT 0"
            )
            cursor.execute(
                "UPDATE clientes SET monto_total = round(monto * 1.20, 2) WHERE monto_total = 0"
            )

        conn.commit()


init_db()


def obtener_clientes_completos():
    conn = get_db()
    clientes = conn.execute(
        "SELECT * FROM clientes ORDER BY id DESC"
    ).fetchall()
    resultado = []

    for c in clientes:
        cliente_dict = dict(c)
        pagos = conn.execute(
            "SELECT * FROM pagos WHERE cliente_id = ? ORDER BY numero ASC",
            (c["id"],),
        ).fetchall()
        cliente_dict["pagos"] = [dict(p) for p in pagos]
        resultado.append(cliente_dict)

    conn.close()
    return resultado


def calcular_fecha(fecha_inicio, numero, frecuencia):
    if frecuencia == "Diaria":
        return fecha_inicio + timedelta(days=numero)
    if frecuencia == "Semanal":
        return fecha_inicio + timedelta(weeks=numero)
    if frecuencia == "Quincenal":
        return fecha_inicio + timedelta(days=15 * numero)
    if frecuencia == "Mensual":
        return fecha_inicio + relativedelta(months=numero)
    return fecha_inicio


# =====================================================
# PLANTILLA HTML
# =====================================================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sistema de Créditos</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f3f4f6; margin: 0; padding: 12px; color: #1f2937; }
        .header { background: #172554; color: white; padding: 12px; text-align: center; border-radius: 8px; margin-bottom: 12px; }
        .nav { display: flex; gap: 4px; margin-bottom: 15px; overflow-x: auto; }
        .nav a { flex: 1; text-align: center; background: #2563eb; color: white; padding: 10px 4px; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 12px; }
        .card { background: white; padding: 14px; border-radius: 8px; margin-bottom: 10px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        .alert-error { background: #fee2e2; color: #dc2626; padding: 10px; border-radius: 6px; margin-bottom: 10px; font-weight: bold; font-size: 13px; }
        input, select, button { width: 100%; padding: 10px; margin: 4px 0 12px 0; border: 1px solid #d1d5db; border-radius: 6px; box-sizing: border-box; font-size: 14px; }
        button { background: #16a34a; color: white; font-weight: bold; border: none; font-size: 15px; cursor: pointer; }
        .btn-ws { background: #25d366; text-decoration: none; display: block; text-align: center; color: white; padding: 10px; border-radius: 6px; font-weight: bold; margin-top: 8px; font-size: 14px; }
        .badge-green { color: #16a34a; font-weight: bold; }
        .badge-red { color: #dc2626; font-weight: bold; }
        .flex-between { display: flex; justify-content: space-between; align-items: center; }
    </style>
</head>
<body>

<div class="header">
    <h3 style="margin:0;">💰 SISTEMA DE CRÉDITOS</h3>
</div>

<div class="nav">
    <a href="/">📋 Clientes</a>
    <a href="/nuevo">👤 Nuevo</a>
    <a href="/pago">💵 Pagar</a>
    <a href="/resumen">📊 Resumen</a>
</div>

{% if error %}
    <div class="alert-error">⚠️ {{ error }}</div>
{% endif %}

{% if vista == 'lista' %}
    <h3>📋 Clientes Registrados</h3>
    {% for c in clientes %}
        {% set pagado = c.pagos | selectattr('pagado') | map(attribute='valor') | sum %}
        {% set saldo = c.monto_total - pagado %}
        <div class="card">
            <div class="flex-between">
                <h4 style="margin:0;">👤 {{ c.nombre }}</h4>
                <a href="/eliminar/{{ c.id }}" onclick="return confirm('¿Seguro deseas eliminar a este cliente?')" style="color:#dc2626; text-decoration:none; font-weight:bold;">🗑️ Eliminar</a>
            </div>
            <p style="font-size:13px; margin:8px 0;">
                <b>Teléfono:</b> {{ c.telefono or 'N/A' }} | <b>ID:</b> {{ c.identificacion or 'N/A' }}<br>
                <b>Capital:</b> ${{ "%.2f"|format(c.monto) }} (+{{ c.interes_porcentaje }}% interés)<br>
                <b>Total a Pagar:</b> ${{ "%.2f"|format(c.monto_total) }} | <b>Saldo:</b> <span class="badge-red">${{ "%.2f"|format(saldo) }}</span><br>
                <b>Cuota Base:</b> ${{ "%.2f"|format(c.valor_cuota) }} ({{ c.frecuencia }})
            </p>
            <details>
                <summary style="font-weight:bold; cursor:pointer;">Ver Plan de Pagos ({{ c.pagos | length }})</summary>
                <ul style="padding-left:18px; font-size:13px;">
                {% for p in c.pagos %}
                    <li style="margin-bottom:4px;">
                        Cuota {{ p.numero }} ({{ p.fecha }}): ${{ "%.2f"|format(p.valor) }} - 
                        {% if p.pagado %}<span class="badge-green">✅ PAGADO</span>{% else %}<span class="badge-red">⏳ PENDIENTE</span>{% endif %}
                    </li>
                {% endfor %}
                </ul>
            </details>
        </div>
    {% else %}
        <p>No hay clientes registrados.</p>
    {% endfor %}

{% elif vista == 'nuevo' %}
    <h3>👤 Registrar Nuevo Cliente</h3>
    <div class="card">
        <form action="/guardar" method="POST">
            <label>Nombre Completo</label>
            <input type="text" name="nombre" placeholder="Ej: Maria Lopez" required>
            
            <label>Teléfono (Con código de país)</label>
            <input type="text" name="telefono" placeholder="Ej: 593991234567">
            
            <label>Cédula / Identificación</label>
            <input type="text" name="identificacion" placeholder="Ej: 0987654321">
            
            <label>Monto prestado (Capital $)</label>
            <input type="number" step="any" name="monto" placeholder="Ej: 500" required>
            
            <label>Tasa de Interés (%)</label>
            <input type="number" step="any" name="interes_porcentaje" value="20" placeholder="Ej: 20" required>

            <label>Número de cuotas</label>
            <input type="number" name="cuotas" placeholder="Ej: 10" required>
            
            <label>Frecuencia de pago</label>
            <select name="frecuencia">
                <option value="Diaria">Diaria</option>
                <option value="Semanal">Semanal</option>
                <option value="Quincenal">Quincenal</option>
                <option value="Mensual">Mensual</option>
            </select>
            
            <label>Fecha de Primera Cuota</label>
            <input type="date" name="fecha_inicio" value="{{ hoy }}" required>
            
            <button type="submit">💾 Guardar Cliente</button>
        </form>
    </div>

{% elif vista == 'pago' %}
    <h3>💵 Registrar Pago</h3>
    <div class="card">
        {% set hay_pendientes = namespace(valor=false) %}
        {% for c in clientes %}
            {% for p in c.pagos %}
                {% if not p.pagado %}
                    {% set hay_pendientes.valor = true %}
                {% endif %}
            {% endfor %}
        {% endfor %}

        {% if not clientes %}
            <p>No hay clientes registrados aún.</p>
        {% elif not hay_pendientes.valor %}
            <p>🎉 ¡Todos los clientes están al día!</p>
        {% else %}
            <form action="/registrar_pago" method="POST">
                <label>Selecciona la cuota a pagar</label>
                <select name="pago_id" required>
                    {% for c in clientes %}
                        {% for p in c.pagos %}
                            {% if not p.pagado %}
                                <option value="{{ c.id }}_{{ p.numero }}">
                                    {{ c.nombre }} - Cuota {{ p.numero }} (${{ "%.2f"|format(p.valor) }}) - Vence: {{ p.fecha }}
                                </option>
                            {% endif %}
                        {% endfor %}
                    {% endfor %}
                </select>
                <button type="submit">✅ Registrar Pago</button>
            </form>
        {% endif %}
    </div>

    {% if recibo %}
        <div class="card" style="border: 2px solid #16a34a; background: #f0fdf4;">
            <h4>📄 Recibo Generado</h4>
            <p><b>Cliente:</b> {{ recibo.cliente }}<br>
            <b>Cuota #:</b> {{ recibo.cuota }}<br>
            <b>Monto Pagado:</b> ${{ "%.2f"|format(recibo.monto) }}<br>
            <b>Saldo Restante:</b> ${{ "%.2f"|format(recibo.saldo) }}</p>

            {% if recibo.telefono %}
                <a href="https://wa.me/{{ recibo.telefono }}?text={{ recibo.mensaje_ws }}" target="_blank" class="btn-ws">
                    📲 Enviar Comprobante por WhatsApp
                </a>
            {% else %}
                <p style="font-size:12px; color:#6b7280;">(Sin teléfono registrado)</p>
            {% endif %}
        </div>
    {% endif %}

{% elif vista == 'resumen' %}
    <h3>📊 Resumen de Cartera</h3>
    <div class="card">
        <p><b>👥 Total Clientes:</b> {{ clientes | length }}</p>
        <p><b>💵 Capital Otorgado:</b> ${{ "%.2f"|format(total_capital) }}</p>
        <p><b>💰 Total con Intereses:</b> ${{ "%.2f"|format(total_creditos) }}</p>
        <p><b>✅ Total Cobrado:</b> ${{ "%.2f"|format(total_cobrado) }}</p>
        <p><b>📌 Saldo Pendiente:</b> <span class="badge-red">${{ "%.2f"|format(total_creditos - total_cobrado) }}</span></p>
    </div>

    <div class="card">
        <h4>💾 Copia de Seguridad</h4>
        <a href="/respaldo" style="text-decoration:none;">
            <button type="button" style="background:#2563eb;">📥 Descargar Base de Datos (creditos.db)</button>
        </a>
    </div>
{% endif %}

</body>
</html>
"""


# =====================================================
# RUTAS DE LA APLICACIÓN
# =====================================================
@app.route("/")
def lista():
    clientes = obtener_clientes_completos()
    return render_template_string(
        HTML_TEMPLATE, vista="lista", clientes=clientes
    )


@app.route("/nuevo")
def nuevo():
    return render_template_string(
        HTML_TEMPLATE, vista="nuevo", hoy=date.today().isoformat()
    )


@app.route("/guardar", methods=["POST"])
def guardar():
    try:
        nombre = request.form.get("nombre", "").strip()
        telefono = (
            request.form.get("telefono", "")
            .replace("+", "")
            .replace(" ", "")
            .strip()
        )
        identificacion = request.form.get("identificacion", "").strip()
        monto = float(request.form.get("monto", "0").replace(",", "."))
        interes_porcentaje = float(
            request.form.get("interes_porcentaje", "20").replace(",", ".")
        )
        cuotas = int(request.form.get("cuotas", "0"))
        frecuencia = request.form.get("frecuencia")
        fecha_inicio = date.fromisoformat(request.form.get("fecha_inicio"))

        if not nombre or monto <= 0 or cuotas <= 0:
            raise ValueError("Llena correctamente los campos obligatorios.")

        monto_total = round(monto * (1 + (interes_porcentaje / 100)), 2)
        valor_base = round(monto_total / cuotas, 2)
        acumulado = 0.0

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO clientes (nombre, telefono, identificacion, monto, interes_porcentaje, monto_total, cuotas, frecuencia, valor_cuota, fecha_inicio)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                nombre,
                telefono,
                identificacion,
                monto,
                interes_porcentaje,
                monto_total,
                cuotas,
                frecuencia,
                valor_base,
                fecha_inicio.isoformat(),
            ),
        )
        cliente_id = cursor.lastrowid

        for num in range(1, cuotas + 1):
            if num == cuotas:
                valor_cuota = round(monto_total - acumulado, 2)
            else:
                valor_cuota = valor_base
                acumulado += valor_cuota

            f_cuota = calcular_fecha(fecha_inicio, num - 1, frecuencia)
            cursor.execute(
                """
                INSERT INTO pagos (cliente_id, numero, fecha, valor, pagado)
                VALUES (?, ?, ?, ?, 0)
            """,
                (cliente_id, num, f_cuota.isoformat(), valor_cuota),
            )

        conn.commit()
        conn.close()
        return redirect("/")

    except Exception as e:
        return render_template_string(
            HTML_TEMPLATE,
            vista="nuevo",
            hoy=date.today().isoformat(),
            error=f"Error: {str(e)}",
        )


@app.route("/pago")
def pago():
    clientes = obtener_clientes_completos()
    return render_template_string(HTML_TEMPLATE, vista="pago", clientes=clientes)


@app.route("/registrar_pago", methods=["POST"])
def registrar_pago():
    try:
        pago_id = request.form.get("pago_id")
        recibo = None

        if pago_id:
            cliente_id, num_cuota = map(int, pago_id.split("_"))
            conn = get_db()

            conn.execute(
                "UPDATE pagos SET pagado = 1 WHERE cliente_id = ? AND numero = ?",
                (cliente_id, num_cuota),
            )
            conn.commit()

            cliente = conn.execute(
                "SELECT * FROM clientes WHERE id = ?", (cliente_id,)
            ).fetchone()
            pagos = conn.execute(
                "SELECT * FROM pagos WHERE cliente_id = ?", (cliente_id,)
            ).fetchall()

            pagado_total = sum(p["valor"] for p in pagos if p["pagado"] == 1)
            saldo_restante = max(0.0, cliente["monto_total"] - pagado_total)
            pago_actual = next(p for p in pagos if p["numero"] == num_cuota)

            texto_ws = (
                f"📄 *COMPROBANTE DE PAGO*\n\n"
                f"Hola *{cliente['nombre']}*, hemos registrado tu pago correctamente:\n"
                f"🔹 *Cuota #: * {num_cuota}/{len(pagos)}\n"
                f"🔹 *Valor Pagado:* ${pago_actual['valor']:.2f}\n"
                f"🔹 *Saldo Pendiente:* ${saldo_restante:.2f}\n\n"
                f"¡Gracias por tu pago puntual! 🙌"
            )

            recibo = {
                "cliente": cliente["nombre"],
                "cuota": num_cuota,
                "monto": pago_actual["valor"],
                "saldo": saldo_restante,
                "telefono": cliente["telefono"],
                "mensaje_ws": urllib.parse.quote(texto_ws),
            }
            conn.close()

        clientes = obtener_clientes_completos()
        return render_template_string(
            HTML_TEMPLATE, vista="pago", clientes=clientes, recibo=recibo
        )

    except Exception as e:
        clientes = obtener_clientes_completos()
        return render_template_string(
            HTML_TEMPLATE,
            vista="pago",
            clientes=clientes,
            error=f"Error al registrar pago: {str(e)}",
        )


@app.route("/eliminar/<int:cliente_id>")
def eliminar(cliente_id):
    conn = get_db()
    conn.execute("DELETE FROM clientes WHERE id = ?", (cliente_id,))
    conn.commit()
    conn.close()
    return redirect("/")


@app.route("/resumen")
def resumen():
    clientes = obtener_clientes_completos()
    total_capital = sum(c["monto"] for c in clientes)
    total_creditos = sum(c["monto_total"] for c in clientes)
    total_cobrado = sum(
        p["valor"] for c in clientes for p in c["pagos"] if p["pagado"]
    )
    return render_template_string(
        HTML_TEMPLATE,
        vista="resumen",
        clientes=clientes,
        total_capital=total_capital,
        total_creditos=total_creditos,
        total_cobrado=total_cobrado,
    )


@app.route("/respaldo")
def respaldo():
    if os.path.exists(DB_NAME):
        return send_file(DB_NAME, as_attachment=True)
    return redirect("/resumen")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
