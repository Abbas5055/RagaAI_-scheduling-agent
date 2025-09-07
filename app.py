import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
import uuid
from pathlib import Path

DATA_DIR = Path("data")
PATIENTS_CSV = DATA_DIR / "patients.csv"
SCHEDULE_XLSX = DATA_DIR / "doctor_schedules.xlsx"
APPTS_XLSX = DATA_DIR / "appointments.xlsx"

NEW_MIN = 60
RETURN_MIN = 30

def load_patients():
    if PATIENTS_CSV.exists():
        df = pd.read_csv(PATIENTS_CSV)
        if "dob" in df.columns:
            df["dob"] = pd.to_datetime(df["dob"], errors="coerce").dt.date
        return df
    cols = ["patient_id","first_name","last_name","dob","email","phone","city","state","zip","insurance_carrier","member_id","group_number","is_returning"]
    return pd.DataFrame(columns=cols)

def load_schedules():
    if SCHEDULE_XLSX.exists():
        df = pd.read_excel(SCHEDULE_XLSX, engine="openpyxl")
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
        df["slot_start"] = pd.to_datetime(df["slot_start"], errors="coerce")
        df["slot_end"] = pd.to_datetime(df["slot_end"], errors="coerce")
        return df
    cols = ["doctor","location","date","slot_start","slot_end","available"]
    return pd.DataFrame(columns=cols)

def load_appointments():
    if APPTS_XLSX.exists():
        df = pd.read_excel(APPTS_XLSX, engine="openpyxl")
        if "appointment_date" in df.columns:
            df["appointment_date"] = pd.to_datetime(df["appointment_date"], errors="coerce").dt.date
        return df
    cols = ["appointment_id","created_at","patient_id","patient_name","dob","email","phone","city","state","zip","doctor","location","visit_type","appointment_date","slot_start","slot_end","insurance_carrier","member_id","group_number","status","forms_sent","reminder_1","reminder_2","reminder_3","cancellation_reason"]
    return pd.DataFrame(columns=cols)

def save_patients(df):
    df.to_csv(PATIENTS_CSV, index=False)

def save_appointments(df):
    df.to_excel(APPTS_XLSX, index=False, engine="openpyxl")

def find_patient(df, first, last, dob):
    if df.empty:
        return None
    mask = (
        df["first_name"].astype(str).str.lower().str.strip() == str(first).strip().lower()
    ) & (
        df["last_name"].astype(str).str.lower().str.strip() == str(last).strip().lower()
    ) & (
        df["dob"] == dob
    )
    matches = df[mask]
    if len(matches) >= 1:
        return matches.iloc[0]
    return None

def visit_duration(is_returning):
    return RETURN_MIN if is_returning else NEW_MIN

def slots_for_doctor(df_sched, doctor, location, day, duration_min):
    if df_sched.empty:
        return []
    day_df = df_sched[(df_sched["doctor"] == doctor) & (df_sched["location"] == location) & (df_sched["date"] == day)]
    if day_df.empty:
        return []
    free = day_df[day_df["available"] == True].sort_values("slot_start")
    suggestions = []
    cur_start = None
    cur_end = None
    for _, row in free.iterrows():
        s = row["slot_start"].to_pydatetime()
        e = row["slot_end"].to_pydatetime()
        if cur_start is None:
            cur_start = s
            cur_end = e
        else:
            if s == cur_end:
                cur_end = e
            else:
                minutes = int((cur_end - cur_start).total_seconds() // 60)
                if minutes >= duration_min:
                    suggestions.append((cur_start.time(), cur_end.time()))
                cur_start = s
                cur_end = e
    if cur_start is not None:
        minutes = int((cur_end - cur_start).total_seconds() // 60)
        if minutes >= duration_min:
            suggestions.append((cur_start.time(), cur_end.time()))
    return suggestions

def book_slot(df_sched, doctor, location, day, start_dt, end_dt):
    mask = (df_sched["doctor"] == doctor) & (df_sched["location"] == location) & (df_sched["date"] == day)
    target = df_sched[mask]
    for idx, row in target.iterrows():
        s = row["slot_start"].to_pydatetime()
        e = row["slot_end"].to_pydatetime()
        if (s < end_dt) and (start_dt < e):
            df_sched.at[idx, "available"] = False
    df_sched.to_excel(SCHEDULE_XLSX, index=False, engine="openpyxl")

st.set_page_config(page_title="RagaAI Scheduler", layout="wide")

theme_css = """
<style>
body {
  background: linear-gradient(180deg, #f6fbff 0%, #eef8ff 100%);
  color: #073048;
  font-family: "Segoe UI", Roboto, "Helvetica Neue", Arial;
}
.container {
  padding: 18px;
}
.card {
  background: white;
  padding: 18px;
  border-radius: 10px;
  box-shadow: 0 6px 18px rgba(3,27,43,0.06);
  margin-bottom: 12px;
}
.progress {
  font-size: 14px;
  color: #2b5876;
  margin-bottom: 8px;
}
.header h2 {
  margin: 0;
  padding: 0;
}
.small {
  color: #4b6b7a;
  font-size: 13px;
}
.input-wide input, .stTextInput>div>div>input {
  height: 44px;
}
.pill {
  display:inline-block;
  padding:6px 10px;
  border-radius:999px;
  font-size:13px;
  font-weight:600;
}
.pill-blue { background:#e6f2fb; color:#0b67a3; }
.pill-green { background:#e8f8f0; color:#0b8a61; }
.pill-red { background:#fde8e8; color:#b02a2a; }
.small-muted { color:#6b8896; font-size:13px; }
.slot-card {
  border:1px solid rgba(11,71,108,0.06);
  padding:10px;
  border-radius:8px;
  margin-bottom:8px;
}
</style>
"""
st.markdown(theme_css, unsafe_allow_html=True)

patients = load_patients()
schedules = load_schedules()
appts = load_appointments()

if "wizard_step" not in st.session_state:
    st.session_state["wizard_step"] = 1
if "intake" not in st.session_state:
    st.session_state["intake"] = {
        "first_name": "",
        "last_name": "",
        "dob": None,
        "email": "",
        "phone": "",
        "city": "",
        "state": "",
        "zip": "",
        "insurance": "",
        "member_id": "",
        "group_no": ""
    }

min_calendar = date(1970,1,1)
max_calendar = date(2025,12,31)

def set_intake_field(key, val):
    st.session_state["intake"][key] = val

def go_next():
    if st.session_state["wizard_step"] < 7:
        st.session_state["wizard_step"] += 1

def go_prev():
    if st.session_state["wizard_step"] > 1:
        st.session_state["wizard_step"] -= 1

header_col1, header_col2 = st.columns([3,1])
with header_col1:
    name_display = st.session_state["intake"]["first_name"]
    hour = datetime.now().hour
    greet = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
    if name_display:
        st.markdown(f'<div class="header card"><h2>{greet}, {name_display}</h2><div class="small-muted">Let us get you booked quickly</div></div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="header card"><h2>{greet}</h2><div class="small-muted">I will take you step by step</div></div>', unsafe_allow_html=True)
with header_col2:
    step = st.session_state["wizard_step"]
    st.markdown(f'<div class="card progress">Step {step} of 7</div>', unsafe_allow_html=True)

st.markdown('<div class="card">', unsafe_allow_html=True)
if st.session_state["wizard_step"] == 1:
    st.markdown('<div style="font-weight:600;font-size:16px;margin-bottom:6px">What is your first name?</div>', unsafe_allow_html=True)
    first = st.text_input("", value=st.session_state["intake"]["first_name"], key="first_name_input", on_change=set_intake_field, args=("first_name", st.session_state.get("first_name_input","")))
    set_intake_field("first_name", st.session_state.get("first_name_input",""))
    cols = st.columns([1,1])
    with cols[0]:
        if st.button("Next"):
            if first:
                go_next()
            else:
                st.error("Please enter first name")
elif st.session_state["wizard_step"] == 2:
    st.markdown('<div style="font-weight:600;font-size:16px;margin-bottom:6px">What is your last name?</div>', unsafe_allow_html=True)
    last = st.text_input("", value=st.session_state["intake"]["last_name"], key="last_name_input", on_change=set_intake_field, args=("last_name", st.session_state.get("last_name_input","")))
    set_intake_field("last_name", st.session_state.get("last_name_input",""))
    cols = st.columns([1,1])
    with cols[0]:
        if st.button("Back"):
            go_prev()
    with cols[1]:
        if st.button("Next"):
            if st.session_state["intake"]["last_name"]:
                go_next()
            else:
                st.error("Please enter last name")
elif st.session_state["wizard_step"] == 3:
    st.markdown('<div style="font-weight:600;font-size:16px;margin-bottom:6px">Date of birth</div>', unsafe_allow_html=True)
    dob_input = st.date_input("", value=st.session_state["intake"]["dob"] or date(1990,1,1), min_value=min_calendar, max_value=max_calendar, key="dob_input")
    set_intake_field("dob", dob_input)
    cols = st.columns([1,1])
    with cols[0]:
        if st.button("Back"):
            go_prev()
    with cols[1]:
        if st.button("Next"):
            if st.session_state["intake"]["dob"]:
                go_next()
            else:
                st.error("Please enter date of birth")
elif st.session_state["wizard_step"] == 4:
    st.markdown('<div style="font-weight:600;font-size:16px;margin-bottom:6px">Contact details</div>', unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        email = st.text_input("Email", value=st.session_state["intake"]["email"], key="email_input")
        set_intake_field("email", st.session_state.get("email_input",""))
    with c2:
        phone = st.text_input("Phone", value=st.session_state["intake"]["phone"], key="phone_input")
        set_intake_field("phone", st.session_state.get("phone_input",""))
    cols = st.columns([1,1])
    with cols[0]:
        if st.button("Back"):
            go_prev()
    with cols[1]:
        if st.button("Next"):
            if st.session_state["intake"]["email"] and st.session_state["intake"]["phone"]:
                go_next()
            else:
                st.error("Please enter contact details")
elif st.session_state["wizard_step"] == 5:
    st.markdown('<div style="font-weight:600;font-size:16px;margin-bottom:6px">Insurance (optional)</div>', unsafe_allow_html=True)
    ins1, ins2 = st.columns(2)
    with ins1:
        ins = st.text_input("Carrier", value=st.session_state["intake"]["insurance"], key="ins_input")
        set_intake_field("insurance", st.session_state.get("ins_input",""))
    with ins2:
        mem = st.text_input("Member ID", value=st.session_state["intake"]["member_id"], key="mem_input")
        set_intake_field("member_id", st.session_state.get("mem_input",""))
    cols = st.columns([1,1])
    with cols[0]:
        if st.button("Back"):
            go_prev()
    with cols[1]:
        if st.button("Next"):
            go_next()
elif st.session_state["wizard_step"] == 6:
    st.markdown('<div style="font-weight:600;font-size:16px;margin-bottom:6px">Preferred doctor and location</div>', unsafe_allow_html=True)
    doctor = st.selectbox("Doctor", options=sorted(schedules["doctor"].unique()) if not schedules.empty else ["Dr. Rao"], key="doctor_select")
    location = st.selectbox("Location", options=sorted(schedules["location"].unique()) if not schedules.empty else ["Main Clinic"], key="location_select")
    st.session_state["selected_doctor"] = doctor
    st.session_state["selected_location"] = location
    cols = st.columns([1,1])
    with cols[0]:
        if st.button("Back"):
            go_prev()
    with cols[1]:
        if st.button("Proceed to schedule"):
            go_next()
elif st.session_state["wizard_step"] == 7:
    st.markdown('<div style="font-weight:600;font-size:16px;margin-bottom:6px">Pick a date and slot</div>', unsafe_allow_html=True)
    day = st.date_input("Appointment date", value=date.today(), min_value=min_calendar, max_value=max_calendar, key="appt_date")
    doctor = st.session_state.get("selected_doctor", sorted(schedules["doctor"].unique())[0] if not schedules.empty else "Dr. Rao")
    location = st.session_state.get("selected_location", sorted(schedules["location"].unique())[0] if not schedules.empty else "Main Clinic")
    is_ret = False
    if st.session_state["intake"]["first_name"] and st.session_state["intake"]["last_name"] and st.session_state["intake"]["dob"]:
        existing = find_patient(patients, st.session_state["intake"]["first_name"], st.session_state["intake"]["last_name"], st.session_state["intake"]["dob"])
        if existing is not None:
            is_ret = True
    duration = visit_duration(is_ret)
    st.markdown(f'<div class="small-muted">Visit duration: {duration} minutes</div>', unsafe_allow_html=True)
    if schedules.empty:
        st.warning("No schedules available. Upload schedules in Admin")
    else:
        suggestions = slots_for_doctor(schedules, doctor, location, day, duration)
        if not suggestions:
            st.error("No contiguous blocks available for chosen date")
        else:
            options = []
            for block_start, block_end in suggestions:
                start_dt = datetime.combine(day, block_start)
                end_dt_block = datetime.combine(day, block_end)
                ptr = start_dt
                while ptr + timedelta(minutes=duration) <= end_dt_block:
                    options.append((ptr, ptr + timedelta(minutes=duration)))
                    ptr += timedelta(minutes=30)
            for i, o in enumerate(options):
                start_str = o[0].strftime("%I:%M %p")
                end_str = o[1].strftime("%I:%M %p")
                col1, col2 = st.columns([3,1])
                with col1:
                    st.markdown(f'<div class="slot-card"><strong>{start_str} - {end_str}</strong><div class="small">Doctor: {doctor} · {location}</div></div>', unsafe_allow_html=True)
                with col2:
                    btn_key = f"book_{i}"
                    if st.button("Book", key=btn_key):
                        start_dt, end_dt = o
                        if existing is None:
                            new_patient = {
                                "patient_id": str(uuid.uuid4()),
                                "first_name": st.session_state["intake"]["first_name"],
                                "last_name": st.session_state["intake"]["last_name"],
                                "dob": st.session_state["intake"]["dob"],
                                "email": st.session_state["intake"]["email"],
                                "phone": st.session_state["intake"]["phone"],
                                "city": st.session_state["intake"]["city"],
                                "state": st.session_state["intake"]["state"],
                                "zip": st.session_state["intake"]["zip"],
                                "insurance_carrier": st.session_state["intake"]["insurance"],
                                "member_id": st.session_state["intake"]["member_id"],
                                "group_number": st.session_state["intake"]["group_no"],
                                "is_returning": False
                            }
                            patients = pd.concat([patients, pd.DataFrame([new_patient])], ignore_index=True)
                            save_patients(patients)
                            patient_id = new_patient["patient_id"]
                            patient_name = f'{new_patient["first_name"]} {new_patient["last_name"]}'
                        else:
                            patient_id = existing["patient_id"]
                            patient_name = f'{existing["first_name"]} {existing["last_name"]}'
                        book_slot(schedules, doctor, location, day, start_dt, end_dt)
                        appt = {
                            "appointment_id": str(uuid.uuid4()),
                            "created_at": datetime.now(),
                            "patient_id": patient_id,
                            "patient_name": patient_name,
                            "dob": st.session_state["intake"]["dob"],
                            "email": st.session_state["intake"]["email"],
                            "phone": st.session_state["intake"]["phone"],
                            "city": st.session_state["intake"]["city"],
                            "state": st.session_state["intake"]["state"],
                            "zip": st.session_state["intake"]["zip"],
                            "doctor": doctor,
                            "location": location,
                            "visit_type": "returning" if is_ret else "new",
                            "appointment_date": day,
                            "slot_start": start_dt,
                            "slot_end": end_dt,
                            "insurance_carrier": st.session_state["intake"]["insurance"],
                            "member_id": st.session_state["intake"]["member_id"],
                            "group_number": st.session_state["intake"]["group_no"],
                            "status": "scheduled",
                            "forms_sent": False,
                            "reminder_1": "pending",
                            "reminder_2": "pending",
                            "reminder_3": "pending",
                            "cancellation_reason": ""
                        }
                        appts = pd.concat([appts, pd.DataFrame([appt])], ignore_index=True)
                        save_appointments(appts)
                        st.success("Appointment booked")
                        st.session_state["wizard_step"] = 8
    cols = st.columns([1,1])
    with cols[0]:
        if st.button("Back"):
            go_prev()
st.markdown('</div>', unsafe_allow_html=True)

if "wizard_step" in st.session_state and st.session_state["wizard_step"] == 8:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div style="font-weight:600;font-size:16px;margin-bottom:6px">Booking complete</div>', unsafe_allow_html=True)
    last_appt = appts.iloc[-1] if not appts.empty else None
    if last_appt is not None:
        status = last_appt["status"]
        if status == "scheduled":
            badge = '<span class="pill pill-blue">Scheduled</span>'
        elif status == "confirmed":
            badge = '<span class="pill pill-green">Confirmed</span>'
        else:
            badge = '<span class="pill pill-red">Cancelled</span>'
        st.markdown(f'{badge}  <div class="small-muted"> {last_appt["patient_name"]} · {last_appt["appointment_date"]} · {pd.to_datetime(last_appt["slot_start"]).strftime("%I:%M %p")}</div>', unsafe_allow_html=True)
        st.markdown('<div style="margin-top:10px;font-weight:600">Reminder preview</div>', unsafe_allow_html=True)
        sms_preview = f"Reminder: Hi {last_appt['patient_name']}, your appointment with {last_appt['doctor']} is on {last_appt['appointment_date']} at {pd.to_datetime(last_appt['slot_start']).strftime('%I:%M %p')}."
        email_preview = f"Subject: Appointment reminder\n\nDear {last_appt['patient_name']},\n\nThis is a reminder for your appointment with {last_appt['doctor']} on {last_appt['appointment_date']} at {pd.to_datetime(last_appt['slot_start']).strftime('%I:%M %p')}.\n\nPlease complete the intake form."
        st.markdown(f'**SMS:** {sms_preview}', unsafe_allow_html=True)
        st.markdown(f'**Email:**<pre style="white-space:pre-wrap">{email_preview}</pre>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown('<div class="card">', unsafe_allow_html=True)
st.subheader("Admin")
admin_cols = st.columns([2,1])
with admin_cols[0]:
    upload_pat = st.file_uploader("Replace patients.csv", type=["csv"])
    if upload_pat is not None:
        dfp = pd.read_csv(upload_pat)
        if "dob" in dfp.columns:
            dfp["dob"] = pd.to_datetime(dfp["dob"], errors="coerce").dt.date
        dfp.to_csv(PATIENTS_CSV, index=False)
        patients = load_patients()
        st.success("Patients replaced")
    upload_sched = st.file_uploader("Replace doctor_schedules.xlsx", type=["xlsx"])
    if upload_sched is not None:
        pd.read_excel(upload_sched, engine="openpyxl").to_excel(SCHEDULE_XLSX, index=False, engine="openpyxl")
        schedules = load_schedules()
        st.success("Schedules replaced")
with admin_cols[1]:
    if st.button("Download appointments.xlsx"):
        if APPTS_XLSX.exists():
            with open(APPTS_XLSX, "rb") as f:
                st.download_button("Download", data=f.read(), file_name="appointments.xlsx")
    if st.button("Reset wizard"):
        st.session_state["wizard_step"] = 1
        st.session_state["intake"] = {
            "first_name": "",
            "last_name": "",
            "dob": None,
            "email": "",
            "phone": "",
            "city": "",
            "state": "",
            "zip": "",
            "insurance": "",
            "member_id": "",
            "group_no": ""
        }
st.markdown('</div>', unsafe_allow_html=True)
