import streamlit as st
import pulp
import pandas as pd
import io
import csv

# --- CORE ALGORITHM ---
def generate_schedule_with_suggestions(num_weeks, slots_per_week_map, employee_needs, employee_preferences, use_seniority=False):
    employees = list(employee_needs.keys())
    weeks = list(range(1, num_weeks + 1))
    
    costs = {}
    for emp in employees:
        costs[emp] = {}
        # Check if the employee left their preferences completely blank
        is_flexible = len(employee_preferences[emp]) == 0
        
        for w in weeks:
            if is_flexible:
                # Give all weeks an equal, lowest-penalty score (1st choice weight)
                costs[emp][w] = 1 
            elif w in employee_preferences[emp]:
                costs[emp][w] = employee_preferences[emp].index(w) + 1
            else:
                costs[emp][w] = 100 
                
    # --- PASS 1: Calculate the absolute optimal team fairness ---
    prob1 = pulp.LpProblem("Pass1_BaseFairness", pulp.LpMinimize)
    x1 = pulp.LpVariable.dicts("assign1", ((emp, w) for emp in employees for w in weeks), cat='Binary')
    
    prob1 += pulp.lpSum(costs[emp][w] * x1[emp, w] for emp in employees for w in weeks)
    
    for emp in employees:
        prob1 += pulp.lpSum(x1[emp, w] for w in weeks) == employee_needs[emp]
    for w in weeks:
        prob1 += pulp.lpSum(x1[emp, w] for emp in employees) <= slots_per_week_map[w]
        
    prob1.solve(pulp.PULP_CBC_CMD(msg=0))
    
    if prob1.status != pulp.LpStatusOptimal:
        return None, None, None
        
    optimal_base_cost = pulp.value(prob1.objective)
    final_variables = x1 
    
    # --- PASS 2: Apply Seniority within the 15% Threshold ---
    if use_seniority:
        prob2 = pulp.LpProblem("Pass2_SeniorityWeighted", pulp.LpMinimize)
        x2 = pulp.LpVariable.dicts("assign2", ((emp, w) for emp in employees for w in weeks), cat='Binary')
        
        total_emps = len(employees)
        weights = {emp: total_emps - i for i, emp in enumerate(employees)}
        
        prob2 += pulp.lpSum(weights[emp] * costs[emp][w] * x2[emp, w] for emp in employees for w in weeks)
        
        for emp in employees:
            prob2 += pulp.lpSum(x2[emp, w] for w in weeks) == employee_needs[emp]
        for w in weeks:
            prob2 += pulp.lpSum(x2[emp, w] for emp in employees) <= slots_per_week_map[w]
            
        prob2 += pulp.lpSum(costs[emp][w] * x2[emp, w] for emp in employees for w in weeks) <= (1.15 * optimal_base_cost)
        
        prob2.solve(pulp.PULP_CBC_CMD(msg=0))
        
        if prob2.status == pulp.LpStatusOptimal:
            final_variables = x2

    # --- EXTRACT RESULTS & CALCULATE SCORECARD ---
    schedule = {w: [] for w in weeks}
    suggestions = {w: [] for w in weeks}
    scorecard = {"1st Choice": 0, "2nd Choice": 0, "3rd Choice": 0, "4th+ Choice": 0, "Flexible": 0, "Unpreferred": 0}
    
    for w in weeks:
        for emp in employees:
            if pulp.value(final_variables[emp, w]) == 1.0:
                is_flexible = len(employee_preferences[emp]) == 0
                
                if is_flexible:
                    schedule[w].append(emp)
                    scorecard["Flexible"] += 1
                elif w in employee_preferences[emp]:
                    schedule[w].append(emp)
                    rank = employee_preferences[emp].index(w) + 1
                    if rank == 1: scorecard["1st Choice"] += 1
                    elif rank == 2: scorecard["2nd Choice"] += 1
                    elif rank == 3: scorecard["3rd Choice"] += 1
                    else: scorecard["4th+ Choice"] += 1
                else:
                    suggestions[w].append(emp)
                    scorecard["Unpreferred"] += 1
                    
    return schedule, suggestions, scorecard

# --- STREAMLIT WEB UI ---

st.set_page_config(page_title="KEN Scheduler", layout="centered")
st.title("Key Equity Navigator (KEN)")
st.write("Fair ROTAs with a Click of a Button")

# 1. Base Parameters
col1, col2 = st.columns(2)
with col1:
    num_weeks = st.number_input("Total Weeks", min_value=1, value=4, step=1)
with col2:
    default_slots = st.number_input("Default Slots Per Week", min_value=1, value=2, step=1)

# 2. Advanced Settings
with st.expander("⚙️ Advanced Settings"):
    use_seniority = st.checkbox("🎖️ Enable Seniority Weighting", help="Favors employees listed at the top, provided it doesn't drop overall team fairness by more than 15%.")
    
    advanced_slots = st.checkbox("📅 Set specific slot capacities for each week individually")
    slots_per_week_map = {}
    
    if advanced_slots:
        st.caption("Override the default capacity for specific weeks below:")
        grid_cols = st.columns(4) 
        for w in range(1, num_weeks + 1):
            with grid_cols[(w - 1) % 4]:
                slots_per_week_map[w] = st.number_input(f"Week {w} Slots", min_value=0, value=default_slots, step=1, key=f"slot_{w}")
    else:
        for w in range(1, num_weeks + 1):
            slots_per_week_map[w] = default_slots

st.divider()

# 3. Data Input
st.subheader("1. Input Employee Data")

uploaded_file = st.file_uploader("Load from CSV (Optional)", type=["csv"])
default_text = "Alice; 2; 1, 2, 4\nBob; 2; 2, 4, 1\nCharlie; 2; \nDiana; 2; 1, 4, 2" # Added Charlie as flexible in default

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

st.write("Format: `Name; Weeks Needed; Pref1, Pref2, Pref3` (Leave preferences blank if flexible)")
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
        
        # Updated to allow missing third section
        if len(parts) < 2:
            st.error(f"Format error on line: {line}. Make sure you have at least a Name and Weeks Needed.")
            error = True
            break
        
        try:
            name = parts[0].strip()
            emp_needs = int(parts[1].strip())
            
            # If they provided preferences, parse them; otherwise, empty list
            emp_prefs = []
            if len(parts) >= 3 and parts[2].strip():
                emp_prefs = [int(p.strip()) for p in parts[2].split(',') if p.strip()]
                
            needs[name] = emp_needs
            preferences[name] = emp_prefs
        except ValueError:
            st.error(f"Value error on line: {line}. Make sure needs and preferences are numbers.")
            error = True
            break
            
    if not error:
        with st.spinner("Calculating optimal schedule..."):
            schedule, suggestions, scorecard = generate_schedule_with_suggestions(num_weeks, slots_per_week_map, needs, preferences, use_seniority)
            
        if schedule is None:
            st.error("ERROR: Impossible constraints. Not enough total slots available to fulfill everyone's required weeks.")
        else:
            st.success("Schedule generated successfully!")
            
            # --- DISPLAY SCORECARD ---
            st.markdown("### 📊 Fairness Scorecard")
            sc_cols = st.columns(6) # Expanded to 6 columns to fit the "Flexible" metric
            sc_cols[0].metric("1st Choices", scorecard["1st Choice"])
            sc_cols[1].metric("2nd Choices", scorecard["2nd Choice"])
            sc_cols[2].metric("3rd Choices", scorecard["3rd Choice"])
            sc_cols[3].metric("4th+ Choices", scorecard["4th+ Choice"])
            sc_cols[4].metric("Flexible", scorecard["Flexible"])
            sc_cols[5].metric("Unpreferred", scorecard["Unpreferred"])
            st.write("") 
            
            # --- DISPLAY SCHEDULE ---
            sched_data = []
            for w in range(1, num_weeks + 1):
                emps = schedule.get(w, [])
                sched_data.append({"Week": f"Week {w}", "Status": "Scheduled", "Employees": ", ".join(emps) if emps else "Empty"})
            
            st.markdown("### 📅 Confirmed Schedule")
            st.table(pd.DataFrame(sched_data))
            
            issues_found = False
            sugg_data = []
            for w in range(1, num_weeks + 1):
                emps = suggestions.get(w, [])
                if emps:
                    issues_found = True
                    sugg_data.append({"Week": f"Week {w}", "Status": "Flagged (Suggested Switch)", "Employees": ", ".join(emps)})
            
            if issues_found:
                st.warning("### ⚠️ Unfilled Weeks & Fairness Suggestions")
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


