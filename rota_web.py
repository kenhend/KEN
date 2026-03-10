import streamlit as st
import pulp
import pandas as pd
import io
import csv

# --- CORE ALGORITHM ---
def generate_schedule_with_suggestions(num_weeks, slots_per_week_map, employee_needs, employee_preferences):
    prob = pulp.LpProblem("Fair_Scheduling_With_Flags", pulp.LpMinimize)
    employees = list(employee_needs.keys())
    weeks = list(range(1, num_weeks + 1))
    
    costs = {}
    for emp in employees:
        costs[emp] = {}
        for w in weeks:
            if w in employee_preferences[emp]:
                costs[emp][w] = employee_preferences[emp].index(w) + 1
            else:
                costs[emp][w] = 100 
                
    x = pulp.LpVariable.dicts("assign", ((emp, w) for emp in employees for w in weeks), cat='Binary')
    
    prob += pulp.lpSum(costs[emp][w] * x[emp, w] for emp in employees for w in weeks)
    
    for emp in employees:
        prob += pulp.lpSum(x[emp, w] for w in weeks) == employee_needs[emp]
        
    # UPDATED CONSTRAINT: Now checks against the specific capacity mapped to each week
    for w in weeks:
        prob += pulp.lpSum(x[emp, w] for emp in employees) <= slots_per_week_map[w]
        
    prob.solve(pulp.PULP_CBC_CMD(msg=0))
    
    if prob.status != pulp.LpStatusOptimal:
        return None, None
        
    schedule = {w: [] for w in weeks}
    suggestions = {w: [] for w in weeks}
    
    for w in weeks:
        for emp in employees:
            if pulp.value(x[emp, w]) == 1.0:
                if w in employee_preferences[emp]:
                    schedule[w].append(emp)
                else:
                    suggestions[w].append(emp)
                    
    return schedule, suggestions

# --- STREAMLIT WEB UI ---

st.set_page_config(page_title="KEN Scheduler", layout="centered")
st.title("KEN: Key Equity Navigator")
st.write("Upload your employee data or type it below to generate an optimal, mathematically fair schedule.")

# 1. Base Parameters
col1, col2 = st.columns(2)
with col1:
    num_weeks = st.number_input("Total Weeks", min_value=1, value=4, step=1)
with col2:
    default_slots = st.number_input("Default Slots Per Week", min_value=1, value=2, step=1)

# 2. Advanced Slot Configuration
st.write("") # Spacer
advanced_slots = st.checkbox("⚙️ Advanced: Set slots for each week individually")
slots_per_week_map = {}

if advanced_slots:
    st.info("Override the default capacity for specific weeks below:")
    # Create a dynamic grid of inputs based on the number of weeks
    grid_cols = st.columns(4) 
    for w in range(1, num_weeks + 1):
        with grid_cols[(w - 1) % 4]:
            slots_per_week_map[w] = st.number_input(f"Week {w} Slots", min_value=0, value=default_slots, step=1, key=f"slot_{w}")
else:
    # If the box isn't checked, apply the default slots to every week
    for w in range(1, num_weeks + 1):
        slots_per_week_map[w] = default_slots

st.divider()

# 3. Data Input
st.subheader("1. Input Employee Data")

uploaded_file = st.file_uploader("Load from CSV (Optional)", type=["csv"])
default_text = "Alice; 2; 1, 2, 4\nBob; 2; 2, 4, 1\nCharlie; 2; 4, 1, 2\nDiana; 2; 1, 4, 2"

if uploaded_file is not None:
    stringio = io.StringIO(uploaded_file.getvalue().decode("utf-8-sig"))
    reader = csv.reader(stringio)
    new_text = ""
    for row in reader:
        if not row or not "".join(row).strip():
            continue
        name = row[0].strip()
        if name.lower() in ["name", "employee"]:
            continue
        needs = row[1].strip() if len(row) > 1 else "0"
        prefs = ", ".join([str(p).strip() for p in row[2:] if str(p).strip()])
        new_text += f"{name}; {needs}; {prefs}\n"
    default_text = new_text.strip()

st.write("Format: `Name; Weeks Needed; Pref1, Pref2, Pref3`")
raw_data = st.text_area("Employee Data Box", value=default_text, height=150)

st.divider()

# 4. Action & Results
st.subheader("2. Generate Schedule")
if st.button("Generate Fair Schedule", type="primary"):
    needs = {}
    preferences = {}
    error = False
    
    lines = raw_data.strip().split('\n')
    for line in lines:
        if not line.strip():
            continue
        parts = line.split(';')
        if len(parts) != 3:
            st.error(f"Format error on line: {line}. Make sure you are using semicolons.")
            error = True
            break
        
        try:
            name = parts[0].strip()
            emp_needs = int(parts[1].strip())
            emp_prefs = [int(p.strip()) for p in parts[2].split(',') if p.strip()]
            needs[name] = emp_needs
            preferences[name] = emp_prefs
        except ValueError:
            st.error(f"Value error on line: {line}. Make sure needs and preferences are numbers.")
            error = True
            break
            
    if not error:
        with st.spinner("Calculating optimal schedule..."):
            # Pass the new dynamic map into the algorithm instead of a static integer
            schedule, suggestions = generate_schedule_with_suggestions(num_weeks, slots_per_week_map, needs, preferences)
            
        if schedule is None:
            st.error("ERROR: Impossible constraints. Not enough total slots available to fulfill everyone's required weeks.")
        else:
            st.success("Schedule generated successfully!")
            
            sched_data = []
            for w in range(1, num_weeks + 1):
                emps = schedule.get(w, [])
                sched_data.append({"Week": f"Week {w}", "Status": "Scheduled", "Employees": ", ".join(emps) if emps else "Empty"})
            
            st.markdown("### Confirmed Schedule")
            st.table(pd.DataFrame(sched_data))
            
            issues_found = False
            sugg_data = []
            for w in range(1, num_weeks + 1):
                emps = suggestions.get(w, [])
                if emps:
                    issues_found = True
                    sugg_data.append({"Week": f"Week {w}", "Status": "Flagged (Suggested Switch)", "Employees": ", ".join(emps)})
            
            if issues_found:
                st.warning("### Unfilled Weeks & Fairness Suggestions")
                st.table(pd.DataFrame(sugg_data))
            else:
                st.info("All slots filled perfectly based on employee preferences!")
                
            output_df = pd.DataFrame(sched_data)
            if issues_found:
                gap_df = pd.DataFrame([{"Week": "---", "Status": "---", "Employees": "---"}])
                output_df = pd.concat([output_df, gap_df, pd.DataFrame(sugg_data)], ignore_index=True)
                
            csv_export = output_df.to_csv(index=False).encode('utf-8')
            
            st.download_button(
                label="Download Results as CSV",
                data=csv_export,
                file_name="KEN_Schedule_Export.csv",
                mime="text/csv",
            )
