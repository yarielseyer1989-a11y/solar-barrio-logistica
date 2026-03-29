# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import psycopg2 # <--- MOTOR DE POSTGRESQL PARA LA NUBE
import os
import requests
from datetime import datetime, timedelta
import plotly.express as px

# --- CONFIGURACIÓN ESTÉTICA ---
st.set_page_config(page_title="Solar Barrio Pro: Logística & Finanzas", page_icon="💰", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stMetric { background-color: #ffffff; padding: 20px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); border-left: 5px solid #2ecc71; }
    .stButton>button { background-color: #2ecc71; color: white; font-weight: bold; border-radius: 8px; }
    </style>
    """, unsafe_allow_html=True)

# --- CONSTANTES Y RUTAS ---
TOKEN_BOT = "8715828197:AAFOcTECqUo-EygBaKA8EMBc8ohkn-S5FbA"
# 🌍 TU LLAVE DE RENDER YA CONFIGURADA
DATABASE_URL = "postgresql://solardb_qsmc_user:e4m42uewjIpJCPeA53UEiVNHzKvHOmq3@dpg-d74gr9vpm1nc738uc8vg-a.frankfurt-postgres.render.com/solardb_qsmc"


# --- LÓGICA DE TIEMPOS Y COSTES ---
def calcular_config(nombre_kit):
    kits = {"Ahorro": (8, "Kit Ahorro"), "Anti-Apagones": (12, "Kit Anti-Apagones"), "Independencia": (16, "Kit Independencia")}
    for k, v in kits.items():
        if k.lower() in str(nombre_kit).lower(): return v
    return (10, "Kit Personalizado")

def sumar_horas_laborales(fecha_inicio, horas):
    curr = fecha_inicio
    rem = horas
    while rem > 0:
        if curr.weekday() >= 5: # Saltar fin de semana
            curr += timedelta(days=(7 - curr.weekday()))
            curr = curr.replace(hour=8, minute=0)
            continue
        if curr.hour < 8: curr = curr.replace(hour=8, minute=0)
        if curr.hour >= 18:
            curr += timedelta(days=1)
            curr = curr.replace(hour=8, minute=0)
            continue
        disp = 18 - curr.hour - (curr.minute / 60.0)
        if rem <= disp:
            curr += timedelta(hours=rem)
            rem = 0
        else:
            rem -= disp
            curr += timedelta(days=1)
            curr = curr.replace(hour=8, minute=0)
            
    # Última comprobación para no caer en fuera de horas
    if curr.hour >= 18:
        curr += timedelta(days=1)
        curr = curr.replace(hour=8, minute=0)
    if curr.weekday() >= 5:
        curr += timedelta(days=(7 - curr.weekday()))
        curr = curr.replace(hour=8, minute=0)
        
    return curr

# --- CARGA DE DATOS DESDE POSTGRESQL ---
def cargar_datos():
    try:
        conn = psycopg2.connect(DATABASE_URL)
        c = conn.cursor()
        c.execute("SELECT id, nombre, chat_id, kit_asignado, fecha_material, estado_obra, brigada, fecha_montaje FROM clientes")
        rows = c.fetchall()
        conn.close()
        
        data = []
        for r in rows:
            data.append({
                'ID': r[0], 'Cliente': r[1], 'ChatID': r[2], 'Kit': r[3],
                'FechaMat': r[4], 'Estado': r[5], 'Brigada': r[6], 'FechaMontaje': r[7]
            })
        return data
    except Exception as e:
        st.error(f"Error cargando Base de Datos: {e}")
        return []

# --- INTERFAZ LATERAL ---
st.sidebar.header("📊 Configuración de Costes")
costo_hora_brigada = st.sidebar.number_input("Coste Mano de Obra (€/hora)", min_value=10, max_value=200, value=50, step=5)

st.sidebar.divider()
st.sidebar.header("⚙️ Operativa")
num_brigadas = st.sidebar.slider("Número de Brigadas Disponibles", 1, 4, 2)
incluir_programados = st.sidebar.checkbox("⚠️ Re-calcular obras ya programadas (Destruye agenda antigua)")

if st.sidebar.button("♻️ Resetear Toda la Agenda"):
    try:
        conn = psycopg2.connect(DATABASE_URL)
        c = conn.cursor()
        c.execute("UPDATE clientes SET estado_obra = 'LISTO PARA PROGRAMAR', brigada = NULL, fecha_montaje = NULL WHERE estado_obra = 'PROGRAMADA'")
        conn.commit()
        conn.close()
        st.sidebar.success("Agenda reseteada. Refresca la página.")
    except Exception as e:
        st.sidebar.error(f"Error al resetear: {e}")

# --- CUERPO PRINCIPAL ---
st.title("💸 Solar Barrio: Optimizador Logístico Inteligente")

raw_data = cargar_datos()
if raw_data:
    bloqueados = []
    nuevos = []
    
    # 1. Separar clientes antiguos (ya programados) de los nuevos
    for p in raw_data:
        est = str(p['Estado']).upper()
        if est == "PROGRAMADA":
            if incluir_programados:
                nuevos.append(p) # Si forzamos recalcular, los metemos como nuevos
            else:
                bloqueados.append(p) # Si no, se bloquean y respetan
        elif est == "LISTO PARA PROGRAMAR" and p['FechaMat'] and str(p['FechaMat']).lower() != 'none':
            nuevos.append(p)
            
    pendientes_mostrar = bloqueados + nuevos
    
    if not pendientes_mostrar:
        st.info("No hay obras pendientes con materiales confirmados o programadas en la Base de Datos.")
    else:
        brigadas = [f"Brigada {i+1}" for i in range(num_brigadas)]
        dispo_brigada = {b: datetime.now().replace(hour=8, minute=0, second=0, microsecond=0) for b in brigadas}
        resultados = []
        
        # 2. POSICIONAR LOS BLOQUEADOS (FIJOS)
        for p in bloqueados:
            b_actual = p.get('Brigada')
            if not b_actual or b_actual not in dispo_brigada: b_actual = brigadas[0]
            
            # Intentar rescatar la fecha guardada para pintarla en el Gantt
            inicio = datetime.now().replace(hour=8, minute=0)
            fin = inicio + timedelta(hours=5)
            try:
                fm = p.get('FechaMontaje', "")
                partes = fm.split(" a ")
                year = datetime.now().year
                inicio = datetime.strptime(f"{partes[0]}/{year}", "%d/%m %H:%M/%Y")
                fin = datetime.strptime(f"{partes[0].split(' ')[0]} {partes[1]}/{year}", "%d/%m %H:%M/%Y")
                
                # Desplazar la disponibilidad de la brigada para que los nuevos entren DESPUÉS de este
                next_d = fin + timedelta(hours=1) if fin.hour < 14 else (fin + timedelta(days=1)).replace(hour=8, minute=0)
                next_d = sumar_horas_laborales(next_d, 0)
                if next_d > dispo_brigada[b_actual]:
                    dispo_brigada[b_actual] = next_d
            except: pass
            
            h_nec, nom_kit = calcular_config(p['Kit'])
            resultados.append({
                'ID': p['ID'], 'Cliente': p['Cliente'], 'Brigada': b_actual, 'Kit': nom_kit, 
                'Inicio': inicio, 'Fin': fin, 'Horas': h_nec, 'Gastos de Mano de Obra (€)': h_nec * costo_hora_brigada,
                'ChatID': p['ChatID'], 'Es_Nuevo': False
            })

        # 3. POSICIONAR LOS NUEVOS (HUECOS LIBRES)
        nuevos.sort(key=lambda x: str(x['FechaMat'])) # Orden de llegada de material
        for p in nuevos:
            b_optima = min(dispo_brigada, key=dispo_brigada.get)
            h_necesarias, nombre_kit = calcular_config(p['Kit'])
            
            try: f_mat = datetime.strptime(str(p['FechaMat']).strip(), "%d/%m/%Y").replace(hour=8, minute=0, second=0, microsecond=0)
            except: f_mat = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0)
            
            inicio = max(dispo_brigada[b_optima], f_mat)
            inicio = sumar_horas_laborales(inicio, 0)
            fin = sumar_horas_laborales(inicio, h_necesarias)
            
            resultados.append({
                'ID': p['ID'], 'Cliente': p['Cliente'], 'Brigada': b_optima, 'Kit': nombre_kit, 
                'Inicio': inicio, 'Fin': fin, 'Horas': h_necesarias, 'Gastos de Mano de Obra (€)': h_necesarias * costo_hora_brigada,
                'ChatID': p['ChatID'], 'Es_Nuevo': True
            })
            
            # Bloquear la brigada para el siguiente
            next_d = fin + timedelta(hours=1) if fin.hour < 14 else (fin + timedelta(days=1)).replace(hour=8, minute=0)
            dispo_brigada[b_optima] = sumar_horas_laborales(next_d, 0)

        # ========================================================
        # 📊 MÉTRICAS FINANCIERAS Y DE TIEMPO
        # ========================================================
        if resultados:
            fecha_minima = min([r['Inicio'] for r in resultados])
            fecha_maxima = max([r['Fin'] for r in resultados])
            duracion_total = fecha_maxima - fecha_minima
            dias_totales = duracion_total.days
            horas_totales = int((duracion_total.total_seconds() % (24 * 3600)) // 3600)
            
            texto_duracion = f"{dias_totales} días, {horas_totales} horas"

            total_coste = sum([r['Gastos de Mano de Obra (€)'] for r in resultados])
            total_horas_trabajo = sum([r['Horas'] for r in resultados])
            
            st.subheader("📊 Resumen del Proyecto Completo")
            c1, c2, c3, c4, c5 = st.columns(5) 
            c1.metric("Obras Planificadas", len(resultados))
            c2.metric("Horas de Trabajo", f"{total_horas_trabajo}h")
            c3.metric("Duración Total (Calendario)", texto_duracion)
            c4.metric("Coste Mano Obra Total", f"{total_coste:,.2f} €", delta_color="inverse")
            c5.metric("Coste Medio por Obra", f"{total_coste/len(resultados):,.2f} €")

        # --- GANTT CON PLOTLY ---
        st.subheader("📅 Cronograma Visual de Montajes")
        df_plot = pd.DataFrame(resultados)
        
        # Etiqueta visual para distinguir los que ya estaban de los nuevos
        df_plot['Etiqueta_Gantt'] = df_plot.apply(lambda x: x['Cliente'] + (" 🌟 (NUEVO)" if x['Es_Nuevo'] else " 🔒 (Fijo)"), axis=1)
        
        fig = px.timeline(
            df_plot, x_start="Inicio", x_end="Fin", y="Brigada", color="Brigada",
            text="Etiqueta_Gantt", color_discrete_sequence=px.colors.qualitative.Pastel
        )
        fig.update_yaxes(autorange="reversed")
        fig.update_traces(textposition='inside', insidetextanchor='middle', marker_line_width=0, opacity=1.0)
        fig.update_layout(title="<b>Planificación Continua (Respeta Fechas Anteriores)</b>", xaxis_title="Fecha y Hora", yaxis_title="", height=400, showlegend=False, font=dict(size=14))
        st.plotly_chart(fig, use_container_width=True)

        # ========================================================
        # 📋 TABLA DE DETALLES RECUPERADA Y FORMATEADA
        # ========================================================
        st.subheader("📋 Desglose de Fechas y Costes por Instalación")
        if resultados:
            df_tabla = pd.DataFrame(resultados).drop(columns=['ID', 'ChatID', 'Es_Nuevo'])
            # Damos formato a las fechas para que se lean bien en la tabla
            df_tabla['Inicio'] = df_tabla['Inicio'].dt.strftime('%d/%m/%Y %H:%M')
            df_tabla['Fin'] = df_tabla['Fin'].dt.strftime('%d/%m/%Y %H:%M')
            
            st.dataframe(df_tabla.style.format({'Gastos de Mano de Obra (€)': '{:,.2f} €'}), use_container_width=True, hide_index=True)

        # --- BOTÓN DE GUARDADO INTELIGENTE ---
        st.info("Los clientes marcados como 🔒 (Fijos) no sufrirán cambios ni recibirán notificaciones.")
        if st.button("🚀 CONFIRMAR E INFORMAR SÓLO A NUEVOS CLIENTES", use_container_width=True):
            try:
                conn = psycopg2.connect(DATABASE_URL)
                cursor = conn.cursor()
                
                notificados = 0
                for r in resultados:
                    if r['Es_Nuevo']: # SOLAMENTE MODIFICAMOS A LOS NUEVOS
                        texto_fecha = f"{r['Inicio'].strftime('%d/%m %H:%M')} a {r['Fin'].strftime('%H:%M')}"
                        # ⚠️ AQUÍ HE CAMBIADO LOS ? POR %s PARA POSTGRESQL
                        cursor.execute("UPDATE clientes SET estado_obra = 'PROGRAMADA', brigada = %s, fecha_montaje = %s WHERE id = %s", (r['Brigada'], texto_fecha, r['ID']))
                        
                        msg = f"☀️ ¡Hola {r['Cliente']}! Tu {r['Kit']} será instalado el {r['Inicio'].strftime('%d/%m')} por la {r['Brigada']}. ¡Gracias por confiar en SOLAR BARRIO!"
                        if r['ChatID'] and str(r['ChatID']).lower() != "none":
                            requests.post(f"https://api.telegram.org/bot{TOKEN_BOT}/sendMessage", data={"chat_id": r['ChatID'], "text": msg})
                        notificados += 1
                
                conn.commit()
                conn.close()
                st.balloons()
                st.success(f"✅ ¡Éxito! Se han guardado y notificado {notificados} nuevos montajes. Los anteriores se han respetado.")
            except Exception as e:
                st.error(f"Error al guardar: {e}")
else:
    st.error("La base de datos está vacía o no se pudo leer.")