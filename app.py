import streamlit as st
from pawpal_system import Owner, Pet, Task, Scheduler, Recurrence
import datetime
from pathlib import Path

from medication_rag import (
    answer_medication_question,
    build_medication_index,
    get_groq_api_key,
    load_environment,
    load_text_file,
)

#add pet and schedule task ( replace placeholders with calls to methods from pawpal_system.py)

st.set_page_config(page_title="PawPal+", page_icon="🐾", layout="centered")
load_environment()

st.title("🐾 PawPal+")

with st.expander("Scenario", expanded=True):
    st.markdown(
        """
**PawPal+** is a pet care planning assistant. It helps a pet owner plan care tasks
for their pet(s) based on constraints like time, priority, and preferences.
The owner can have multiple pets, and each pet can have multiple care tasks (e.g., walks, feeding, playtime).
The system should generate a daily schedule that orders tasks in a way that respects their timing and priority
"""
    )

st.divider()

# --- Session state initialization ---
if "scheduler" not in st.session_state:
    st.session_state.scheduler = Scheduler(owner=Owner(name=""))
if "next_pet_id" not in st.session_state:
    st.session_state.next_pet_id = 1
if "next_task_id" not in st.session_state:
    st.session_state.next_task_id = 1
if "medication_index" not in st.session_state:
    st.session_state.medication_index = None
if "medication_source_name" not in st.session_state:
    st.session_state.medication_source_name = ""

scheduler: Scheduler = st.session_state.scheduler

st.subheader("Owner")
owner_name = st.text_input("Owner name", value=scheduler.owner.name or "Jordan")
if owner_name != scheduler.owner.name:
    scheduler.owner.enter_name(owner_name)

st.markdown("### Add a Pet")
with st.form("add_pet_form"):
    pet_name = st.text_input("Pet name", value="Mochi")
    breed = st.text_input("Breed / Species", value="Labrador")
    age = st.number_input("Age (years)", min_value=0, max_value=30, value=2)
    submitted_pet = st.form_submit_button("Add Pet")

if submitted_pet:
    new_pet = Pet(
        id=st.session_state.next_pet_id,
        name=pet_name,
        breed=breed,
        age=int(age),
    )
    try:
        # Owner.add_pet() registers the pet and prevents duplicate IDs
        scheduler.add_pet(new_pet)
        st.session_state.next_pet_id += 1
        st.success(f"Added pet: {pet_name}")
    except ValueError as e:
        st.error(str(e))

pets = scheduler.get_pets()
if pets:
    st.write("Registered pets:")
    st.table([{"ID": p.id, "Name": p.name, "Breed": p.breed, "Age": p.age} for p in pets])
else:
    st.info("No pets registered yet.")

st.markdown("### Schedule a Task")
if not pets:
    st.warning("Add a pet first before scheduling tasks.")
else:
    pet_options = {f"{p.name} (ID {p.id})": p.id for p in pets}
    with st.form("add_task_form"):
        selected_pet_label = st.selectbox("Select pet", list(pet_options.keys()))
        task_desc = st.text_input("Task description", value="Morning walk")
        task_date = st.date_input("Date", value=datetime.date.today())
        task_time = st.time_input("Start time", value=datetime.time(8, 0))
        duration = st.number_input("Duration (minutes)", min_value=1, max_value=240, value=20)
        priority = st.selectbox("Priority", ["low", "medium", "high"], index=2)
        recurrence_value = st.selectbox(
            "Recurrence",
            [Recurrence.ONCE.value, Recurrence.DAILY.value, Recurrence.WEEKLY.value],
            index=0,
            help="Set this task to repeat automatically when you mark it complete.",
        )
        submitted_task = st.form_submit_button("Add Task")

    if submitted_task:
        start_dt = datetime.datetime.combine(task_date, task_time)
        new_task = Task(
            id=st.session_state.next_task_id,
            description=task_desc,
            start_time=start_dt,
            duration_mins=int(duration),
            priority=priority,
            recurrence=Recurrence(recurrence_value),
        )
        pet_id = pet_options[selected_pet_label]
        conflicts = scheduler.detect_conflicts(new_task)  # Get detailed conflict info instead of boolean
        try:
            # Scheduler.add_task_to_pet() looks up the pet by ID and calls pet.add_task()
            scheduler.add_task_to_pet(pet_id, new_task)
            st.session_state.next_task_id += 1
            if conflicts:
                # Display each conflict as a separate warning with contextual details
                st.warning(f"Task added, but **{len(conflicts)} conflict(s) detected**:")
                for conflict in conflicts:
                    st.warning(conflict.warning_message())
            else:
                st.success(f"'{task_desc}' scheduled for {start_dt.strftime('%b %d at %H:%M')}.")
        except ValueError as e:
            st.error(str(e))

st.divider()

st.subheader("Upcoming Schedule")
st.caption("Calls Scheduler.get_upcoming_tasks() — returns incomplete tasks sorted by start time.")

# Scheduler.get_upcoming_tasks() sorts by start_time and excludes completed tasks
upcoming = scheduler.get_upcoming_tasks()
if upcoming:
    st.table([
        {
            "Description": t.description,
            "Start": t.start_time.strftime("%Y-%m-%d %H:%M"),
            "End": t.end_time.strftime("%H:%M"),
            "Duration (min)": t.duration_mins,
            "Priority": t.priority,
            "Recurrence": t.recurrence.value,
        }
        for t in upcoming
    ])

    task_options = {
        f"{t.description} | {t.start_time.strftime('%Y-%m-%d %H:%M')} | {t.recurrence.value}": t
        for t in upcoming
    }
    with st.form("mark_complete_form"):
        st.markdown("### Mark Task Complete")
        selected_task_label = st.selectbox(
            "Select an upcoming task",
            list(task_options.keys()),
        )
        submitted_complete = st.form_submit_button("Mark Complete")

    if submitted_complete:
        selected_task = task_options[selected_task_label]
        updated = scheduler.mark_task_complete(task_id=selected_task.id)
        if updated:
            st.success(
                f"Marked '{selected_task.description}' complete. "
                "If recurring, the next occurrence was created automatically."
            )
            st.rerun()
        else:
            st.error("Unable to mark task complete. Please refresh and try again.")
else:
    st.info("No upcoming tasks. Add tasks above.")

st.divider()

st.subheader("Medication Assistant (TXT + Groq)")
st.caption("Upload medication instructions, retrieve relevant lines, and get a clear answer.")

default_key_present = bool(get_groq_api_key())
if default_key_present:
    st.info("Using GROQ_API_KEY from environment (.env).")
else:
    st.warning("GROQ_API_KEY is missing from .env. LLM answers will fall back to local TXT output.")

sample_file = Path("assets/sample_medication.txt")
uploaded_file = st.file_uploader("Upload medication TXT file", type=["txt"])

load_sample_col, clear_col = st.columns(2)
with load_sample_col:
    load_sample_clicked = st.button("Load sample medication file")
with clear_col:
    clear_index_clicked = st.button("Clear medication index")

if clear_index_clicked:
    st.session_state.medication_index = None
    st.session_state.medication_source_name = ""
    st.success("Medication index cleared.")

if load_sample_clicked:
    if sample_file.exists():
        sample_text = load_text_file(sample_file)
        st.session_state.medication_index = build_medication_index(sample_text, sample_file.name)
        st.session_state.medication_source_name = sample_file.name
        st.success(f"Loaded {sample_file.name}")
    else:
        st.error("Sample medication file is missing in assets/.")

if uploaded_file is not None and st.button("Index uploaded file"):
    text = uploaded_file.getvalue().decode("utf-8", errors="replace")
    try:
        st.session_state.medication_index = build_medication_index(text, uploaded_file.name)
        st.session_state.medication_source_name = uploaded_file.name
        st.success(f"Indexed {uploaded_file.name}")
    except ValueError as exc:
        st.error(str(exc))

if st.session_state.medication_index is not None:
    st.markdown(f"Source file: **{st.session_state.medication_source_name}**")

    question = st.text_input(
        "Ask medication question",
        placeholder="What medicine should pet1 get at 18:00?",
        key="medication_question",
    )
    
    compare_answers = st.checkbox("Compare: Show both local TXT answer and Groq answer")
    ask_clicked = st.button("Ask medication assistant")

    if ask_clicked:
        try:
            result = answer_medication_question(
                question,
                st.session_state.medication_index,
                include_local_fallback=compare_answers,
            )
            st.markdown("### Answer")

            key_source = result.get("key_source", "unknown")
            key_fingerprint = result.get("key_fingerprint")
            if key_fingerprint:
                st.caption(f"Active key source: {key_source} ({key_fingerprint})")
            else:
                st.caption(f"Active key source: {key_source}")

            if result.get("answer_source") == "groq":
                st.info("Groq answer used.")
            elif bool(get_groq_api_key()):
                st.warning("Groq call failed. Showing local TXT fallback.")
            else:
                st.warning("No API key found. Showing local TXT fallback.")

            if result.get("groq_error"):
                st.caption(f"Groq error: {result['groq_error']}")

            if compare_answers and "local_answer" in result:
                col1, col2 = st.columns(2)
                with col1:
                    st.subheader("From TXT File")
                    st.write(result["local_answer"])
                with col2:
                    st.subheader("Groq")
                    if result.get("groq_answer"):
                        st.write(result["groq_answer"])
                    else:
                        st.write("Groq response unavailable for this request.")
            else:
                st.write(result["answer"])

            st.markdown("### Retrieved source lines")
            st.code(result["context"])
        except ValueError as exc:
            st.error(str(exc))
else:
    st.info("Load sample medication file or upload your own TXT file to start medication Q&A.")