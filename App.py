import streamlit as st
import pandas as pd
import datetime
import os
import bcrypt
import time
import calendar
from io import BytesIO
from sqlalchemy import create_engine, text, MetaData, Table, Column, Integer, String, Boolean, Date, DateTime
from sqlalchemy.pool import NullPool  # Add this import

# ==================== CONFIGURATION ====================
try:
    DB_USER = st.secrets["database"]["DB_USER"]
    DB_PASSWORD = st.secrets["database"]["DB_PASSWORD"]
    DB_HOST = st.secrets["database"]["DB_HOST"]
    DB_PORT = st.secrets["database"]["DB_PORT"]
    DB_NAME = st.secrets["database"]["DB_NAME"]
except Exception:
    # Use your actual credentials
    st.error("❌ Database configuration not found in secrets")
    st.error("Please configure your database credentials in Streamlit secrets")
    st.stop()

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# ==================== IMPROVED DATABASE CONNECTION ====================
@st.cache_resource
def get_db_connection():
    try:
        # Use NullPool to avoid connection pooling issues
        engine = create_engine(
            DATABASE_URL,
            poolclass=NullPool,  # Disable connection pooling
            connect_args={
                'connect_timeout': 10,
                'application_name': 'streamlit_app'
            }
        )
        
        # Test connection with timeout
        with engine.connect() as conn:
            conn.execute(text("CREATE SCHEMA IF NOT EXISTS attendance"))
            conn.commit()
        
        st.success("✅ Database connected successfully!")
        return engine
        
    except Exception as e:
        st.error(f"❌ Error connecting to database: {e}")
        st.info("💡 Tips to fix:")
        st.info("1. Check if your database credentials are correct")
        st.info("2. Make sure the database server is running")
        st.info("3. Wait a few minutes for connections to reset")
        st.info("4. Contact your database provider if issue persists")
        return None

def execute_query(query, params=None):
    engine = get_db_connection()
    if engine is None:
        return None
    try:
        with engine.connect() as conn:
            result = conn.execute(text(query), params or {})
            if query.strip().upper().startswith("SELECT"):
                return result.fetchall()
            else:
                conn.commit()
                return True
    except Exception as e:
        st.error(f"Database error: {e}")
        return None
    finally:
        # Explicitly dispose of connection
        engine.dispose()

def read_table(table_name):
    engine = get_db_connection()
    if engine is None:
        return pd.DataFrame()
    try:
        query = f"SELECT * FROM attendance.{table_name}"
        df = pd.read_sql(query, engine)
        return df
    except Exception as e:
        st.warning(f"Error reading from table {table_name}: {e}")
        return pd.DataFrame()
    finally:
        engine.dispose()

def write_table(table_name, df):
    engine = get_db_connection()
    if engine is None:
        return False
    try:
        df.to_sql(table_name, engine, if_exists='replace', index=False, schema='attendance')
        return True
    except Exception as e:
        st.error(f"Error writing to table {table_name}: {e}")
        return False
    finally:
        engine.dispose()

# ==================== SIMPLIFIED INITIALIZATION ====================
def initialize_system():
    # Show connection status
    st.info("🔄 Connecting to database...")
    
    engine = get_db_connection()
    if engine is None:
        st.error("Cannot connect to database. System initialization failed.")
        st.stop()  # Stop execution if no database connection
    
    # Create tables only if they don't exist
    try:
        with engine.connect() as conn:
            # Create tables one by one with error handling
            tables = [
                """CREATE TABLE IF NOT EXISTS attendance.shifts (
                    ID SERIAL PRIMARY KEY,
                    Name VARCHAR(255) NOT NULL
                )""",
                """CREATE TABLE IF NOT EXISTS attendance.sections (
                    ID SERIAL PRIMARY KEY,
                    Name VARCHAR(255) NOT NULL,
                    Description VARCHAR(500)
                )""",
                """CREATE TABLE IF NOT EXISTS attendance.departments (
                    ID SERIAL PRIMARY KEY,
                    Name VARCHAR(255) NOT NULL,
                    Section_ID INTEGER,
                    Description VARCHAR(500)
                )""",
                """CREATE TABLE IF NOT EXISTS attendance.users (
                    ID SERIAL PRIMARY KEY,
                    Name VARCHAR(255) NOT NULL,
                    Username VARCHAR(255) UNIQUE NOT NULL,
                    Password VARCHAR(255) NOT NULL,
                    Role VARCHAR(50) NOT NULL,
                    Active BOOLEAN DEFAULT TRUE,
                    Assigned_Section VARCHAR(255),
                    Assigned_Shift VARCHAR(255)
                )""",
                """CREATE TABLE IF NOT EXISTS attendance.workers (
                    ID SERIAL PRIMARY KEY,
                    Name VARCHAR(255) NOT NULL,
                    Section VARCHAR(255),
                    Department VARCHAR(255),
                    Shift VARCHAR(255),
                    Active BOOLEAN DEFAULT TRUE
                )""",
                """CREATE TABLE IF NOT EXISTS attendance.attendance (
                    ID SERIAL PRIMARY KEY,
                    Worker_ID INTEGER,
                    Worker_Name VARCHAR(255) NOT NULL,
                    Date DATE NOT NULL,
                    Section VARCHAR(255),
                    Department VARCHAR(255),
                    Shift VARCHAR(255),
                    Status VARCHAR(50) NOT NULL,
                    Timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )"""
            ]
            
            for table_sql in tables:
                try:
                    conn.execute(text(table_sql))
                    conn.commit()
                except Exception as e:
                    st.warning(f"Table creation warning: {e}")
                    continue
        
        st.success("✅ Database initialized successfully!")
        
        # Insert default data
        insert_default_data()
        
    except Exception as e:
        st.error(f"Error during initialization: {e}")
    finally:
        engine.dispose()

def insert_default_data():
    """Insert default data only if tables are empty"""
    # Default shifts
    if read_table("shifts").empty:
        write_table("shifts", pd.DataFrame({
            'ID': [1, 2, 3],
            'Name': ['Morning', 'Afternoon', 'General']
        }))
    
    # Default sections
    if read_table("sections").empty:
        write_table("sections", pd.DataFrame({
            'ID': [1, 2, 3],
            'Name': ['Liquid Section', 'Solid Section', 'Utility Section'],
            'Description': ['Liquid manufacturing', 'Solid manufacturing', 'Utility services']
        }))
    
    # Default departments
    if read_table("departments").empty:
        write_table("departments", pd.DataFrame({
            'ID': [1, 2, 3, 4],
            'Name': ['Mixing', 'Filling', 'Packaging', 'Maintenance'],
            'Section_ID': [1, 1, 2, 3],
            'Description': ['Mixing department', 'Filling department', 'Packaging department', 'Maintenance department']
        }))
    
    # Default admin user
    if read_table("users").empty:
        hashed_password = bcrypt.hashpw("admin123".encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        users_df = pd.DataFrame([{
            'ID': 1,
            'Name': 'Admin User',
            'Username': 'admin',
            'Password': hashed_password,
            'Role': 'Admin',
            'Active': True,
            'Assigned_Section': '',
            'Assigned_Shift': ''
        }])
        write_table("users", users_df)
        st.info("🔐 Default admin user created: username='admin', password='admin123'")

# ==================== AUTHENTICATION ====================
def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check a plain password against the stored bcrypt hash"""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False

def login(username: str, password: str) -> bool:
    """Verify user login credentials against the database"""
    try:
        users_df = read_table("users")
        if users_df.empty:
            st.error("No users found in database")
            return False
        
        # Normalize Active column
        users_df = normalize_active_column(users_df, 'Active')
        
        # Find user
        user = users_df[
            (users_df['Username'] == username) &
            (users_df['Active'].isin(["TRUE", "YES", "1"]))
        ]
        
        if not user.empty:
            stored_hash = user.iloc[0]['Password']
            if verify_password(password, stored_hash):
                st.session_state["logged_in"] = True
                st.session_state["username"] = username
                st.session_state["role"] = user.iloc[0]['Role']
                st.session_state["user_id"] = user.iloc[0]['ID']
                return True
        
        return False
    except Exception as e:
        st.error(f"Login error: {e}")
        return False

# ==================== MOBILE RESPONSIVENESS ====================
def mobile_responsive_css():
    return """
    <style>
    /* Mobile responsiveness */
    @media (max-width: 768px) {
        .main .block-container {
            padding-left: 1rem;
            padding-right: 1rem;
            max-width: 100%;
        }
        
        div[data-testid="stHorizontalBlock"] > div {
            width: 100% !important;
            margin-bottom: 1rem;
        }
        
        .stDataFrame {
            overflow-x: auto;
            display: block;
            white-space: nowrap;
        }
        
        .stTextInput, .stSelectbox, .stDateInput, .stTimeInput, .stNumberInput {
            margin-bottom: 1rem;
        }
        
        .stButton > button {
            width: 100%;
            margin-bottom: 0.5rem;
        }
        
        .stRadio > div {
            flex-direction: column;
        }
        
        .stRadio > div > label {
            margin-bottom: 0.5rem;
        }
        
        .streamlit-expanderHeader {
            font-size: 1rem;
            padding: 0.5rem 0;
        }
        
        div[data-testid="stMetric"] {
            margin-bottom: 1rem;
        }
        
        .stTabs > div > div > div > button {
            font-size: 0.8rem;
            padding: 0.5rem;
        }
    }
    </style>
    """

# ==================== UTILITIES ====================
def normalize_active_column(df, col='Active'):
    if col not in df.columns:
        df[col] = True
    df[col] = df[col].astype(str).str.strip().str.upper()
    return df

def dataframe_to_excel_bytes(df: pd.DataFrame):
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
    bio.seek(0)
    return bio

# ==================== AUTHENTICATION PAGE ====================
def login_page():
    st.title("🔐 Company Attendance System")
    st.markdown("---")
    
    # Add database connection status
    with st.expander("🔧 Database Connection Status"):
        if get_db_connection():
            st.success("✅ Database connected successfully!")
        else:
            st.error("❌ Cannot connect to database")
            st.info("Please check your credentials and try again")
    
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.subheader("Login")
        username = st.text_input("Username", key="login_username")
        password = st.text_input("Password", type="password", key="login_password")
        
        if st.button("Login", type="primary", use_container_width=True):
            if username and password:
                if login(username, password):
                    st.success(f"Welcome, {username}!")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("Invalid credentials or account inactive")
            else:
                st.error("Please enter both username and password")

# ==================== SIMPLIFIED DASHBOARDS ====================
def admin_dashboard():
    st.title("🔧 Admin Dashboard")
    st.info("Welcome to Admin Dashboard - Basic functionality available")
    
    tab1, tab2 = st.tabs(["👥 Users", "👷 Workers"])
    
    with tab1:
        st.subheader("User Management")
        users_df = read_table("users")
        if not users_df.empty:
            st.dataframe(users_df[['ID', 'Name', 'Username', 'Role', 'Active']], use_container_width=True)
        else:
            st.info("No users found")
    
    with tab2:
        st.subheader("Worker Management")
        workers_df = read_table("workers")
        if not workers_df.empty:
            st.dataframe(workers_df, use_container_width=True)
        else:
            st.info("No workers found")

def supervisor_dashboard():
    st.title("👷 Supervisor Dashboard")
    st.info("Welcome to Supervisor Dashboard")
    
    # Simple attendance view
    attendance_df = read_table("attendance")
    if not attendance_df.empty:
        st.subheader("Recent Attendance")
        st.dataframe(attendance_df.tail(10), use_container_width=True)
    else:
        st.info("No attendance records found")

def hr_dashboard():
    st.title("📊 HR Dashboard")
    st.info("Welcome to HR Dashboard")
    
    # Simple stats
    workers_df = read_table("workers")
    attendance_df = read_table("attendance")
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Total Workers", len(workers_df) if not workers_df.empty else 0)
    with col2:
        st.metric("Attendance Records", len(attendance_df) if not attendance_df.empty else 0)

# ==================== MAIN APP ====================
def main():
    # Apply mobile responsive CSS
    st.markdown(mobile_responsive_css(), unsafe_allow_html=True)
    
    # Initialize session state
    if 'logged_in' not in st.session_state:
        st.session_state.logged_in = False
        st.session_state.username = None
        st.session_state.role = None
        st.session_state.user_id = None
    
    # Initialize system
    initialize_system()
    
    # Check login status
    if not st.session_state.logged_in:
        login_page()
    else:
        # Sidebar with logout
        with st.sidebar:
            st.write(f"Logged in as: **{st.session_state.username}** ({st.session_state.role})")
            if st.button("Logout"):
                for key in list(st.session_state.keys()):
                    del st.session_state[key]
                st.rerun()
        
        # Role-based dashboard
        if st.session_state.role == "Admin":
            admin_dashboard()
        elif st.session_state.role == "Supervisor":
            supervisor_dashboard()
        elif st.session_state.role == "HR":
            hr_dashboard()
        else:
            st.error("Invalid role. Please contact administrator.")

if __name__ == "__main__":
    main()