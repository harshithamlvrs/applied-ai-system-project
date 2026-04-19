#import classes from the pawpal_system.py file
from pawpal_system import Owner, Pet, Task, Scheduler, Recurrence
import streamlit as st
from medication_rag import get_groq_api_key, load_environment

load_environment()
if not get_groq_api_key():
    print("WARNING: GROQ_API_KEY not found. LLM features are disabled.")

st.set_page_config(page_title="PawPal+", page_icon="🐾", layout="centered")
st.title("🐾 PawPal+")

#create an Owner and 2 pets with 3 tasks at different times per pet
#change pet 1 to a bird named Shuka and pet 2 to a monkey named Dadi
from datetime import datetime

# Create owner and pets
owner = Owner(name="Krishna")
pet1 = Pet(id=1, name="Shuka", breed="Parakeet Parrot", age=6)
pet2 = Pet(id=2, name="Dadi", breed="Capuchin Monkey", age=4)

# Create tasks OUT OF ORDER (not in chronological sequence)
task1 = Task(id=1, description="Morning walk", start_time=datetime(2026, 3, 29, 7, 0), duration_mins=30, priority="high")
task3 = Task(id=3, description="Playtime", start_time=datetime(2026, 3, 29, 10, 0), duration_mins=20, priority="low")
task2 = Task(id=2, description="Feed breakfast", start_time=datetime(2026, 3, 29, 8, 0), duration_mins=15, priority="high")
task6 = Task(id=6, description="Vet appointment", start_time=datetime(2026, 3, 29, 11, 0), duration_mins=60, priority="high")

task5 = Task(id=5, description="Grooming", start_time=datetime(2026, 3, 29, 9, 0), duration_mins=25, priority="medium")
task4 = Task(id=4, description="Feed breakfast", start_time=datetime(2026, 3, 29, 8, 0), duration_mins=20, priority="high")
task8 = Task(id=8, description="Playtime", start_time=datetime(2026, 3, 29, 18, 0), duration_mins=30, priority="low")
task7 = Task(id=7, description="Evening walk", start_time=datetime(2026, 3, 29, 17, 0), duration_mins=30, priority="medium")

# Add tasks to pets (intentionally unordered)
pet1.add_task(task1)
pet1.add_task(task2)
pet1.add_task(task3)
pet1.add_task(task6)

pet2.add_task(task4)
pet2.add_task(task5)
pet2.add_task(task6)
pet2.add_task(task7)
pet2.add_task(task8)

owner.add_pet(pet1)
owner.add_pet(pet2)
scheduler = Scheduler(owner=owner)

# ============ DEMO 1: Using get_upcoming_tasks() to sort by time ============
print("="*60)
print("DEMO 1: Global upcoming tasks (sorted by start time)")
print("="*60)
upcoming = scheduler.get_upcoming_tasks()
for task in upcoming:
    pet = next(p for p in owner.pets if task in p.tasks)
    print(f"{task.start_time.strftime('%H:%M')} - {task.description:20} [{pet.name:6}] Priority: {task.priority}")

# ============ DEMO 2: Filter tasks by pet name ============
print("\n" + "="*60)
print("DEMO 2: Filter tasks for Shuka only")
print("="*60)
shuka_tasks = scheduler.filter_tasks(pet_name="Shuka")
for task in sorted(shuka_tasks, key=lambda t: t.start_time):
    print(f"{task.start_time.strftime('%H:%M')} - {task.description:20} Priority: {task.priority}")

# ============ DEMO 3: Filter by completion status ============
print("\n" + "="*60)
print("DEMO 3: Mark a task complete, then filter completed vs. incomplete")
print("="*60)
scheduler.mark_task_complete(task_id=1)
completed = scheduler.filter_tasks(is_completed=True)
incomplete = scheduler.filter_tasks(is_completed=False)
print(f"Completed tasks: {len(completed)}")
for task in completed:
    print(f"  ✓ {task.description}")
print(f"Incomplete tasks: {len(incomplete)}")
for task in sorted(incomplete, key=lambda t: t.start_time)[:3]:
    print(f"  ○ {task.description} at {task.start_time.strftime('%H:%M')}")

# ============ DEMO 4: Conflict detection (lightweight, non-crashing) ============
print("\n" + "="*60)
print("DEMO 4: Detect conflicts when tasks overlap (same-time collision)")
print("="*60)

# Attempt to add a task that overlaps with existing tasks
conflict_task = Task(
    id=100,
    description="Vet check",
    start_time=datetime(2026, 3, 29, 8, 15),  # Overlaps with task2 (8:00-8:15) and task4 (8:00-8:20)
    duration_mins=30,
    priority="high"
)

conflicts = scheduler.detect_conflicts(conflict_task)
if conflicts:
    print(f"\n⚠️  {len(conflicts)} conflict(s) detected:")
    for conflict in conflicts:
        print(f"   {conflict.warning_message()}")
else:
    print("No conflicts detected.")

print("\n" + "="*60)
print("DEMO 5: Add task without conflicts")
print("="*60)
safe_task = Task(
    id=101,
    description="Evening playtime",
    start_time=datetime(2026, 3, 29, 19, 0),
    duration_mins=20,
    priority="low"
)

safe_conflicts = scheduler.detect_conflicts(safe_task)
if not safe_conflicts:
    print(f"✓ No conflicts for '{safe_task.description}' at {safe_task.start_time.strftime('%H:%M')}")
else:
    print("Unexpected conflicts found.")


#command to create a new command to enter in teh terminal to create a new file tests/test_pawpal.py
# python -m pytest tests/test_pawpal.py
