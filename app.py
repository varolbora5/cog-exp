from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import datetime
import os
import uuid
import time
from dotenv import load_dotenv
from couchbase.cluster import Cluster
from couchbase.options import ClusterOptions, ClusterTimeoutOptions
from couchbase.auth import PasswordAuthenticator
from couchbase.exceptions import CouchbaseException, UnAmbiguousTimeoutException

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__, static_folder='./')
CORS(app)  # Enable CORS for all routes

# Get Couchbase configuration from environment variables
CB_USERNAME = os.getenv("CB_USERNAME", "")
CB_PASSWORD = os.getenv("CB_PASSWORD", "")
CB_BUCKET = os.getenv("CB_BUCKET", "")
CB_SERVER = os.getenv("CB_SERVER", "")
CB_CONNECT_TIMEOUT = int(os.getenv("CB_CONNECT_TIMEOUT", "30"))  # 30 second default

# Initialize variables to be used globally
cluster = None
bucket = None
collection = None
use_backup_storage = False

# Function to establish Couchbase connection
def connect_to_couchbase():
    global cluster, bucket, collection, use_backup_storage
    
    try:
        auth = PasswordAuthenticator(CB_USERNAME, CB_PASSWORD)
        
        # Configure timeout options
        timeout_options = ClusterTimeoutOptions(
            connect_timeout=datetime.timedelta(seconds=CB_CONNECT_TIMEOUT),
            kv_timeout=datetime.timedelta(seconds=10)
        )
        
        # Create cluster options with timeout settings
        options = ClusterOptions(auth, timeout_options=timeout_options)
        
        # Connect to cluster with retry logic
        max_retries = 3
        for attempt in range(max_retries):
            try:
                print(f"Connecting to Couchbase (attempt {attempt+1}/{max_retries})...")
                cluster = Cluster(CB_SERVER, options)
                bucket = cluster.bucket(CB_BUCKET)
                collection = bucket.default_collection()
                print("Successfully connected to Couchbase")
                return True
            except UnAmbiguousTimeoutException as e:
                print(f"Timeout connecting to Couchbase (attempt {attempt+1}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2)  # Wait before retrying
                else:
                    raise
        
    except UnAmbiguousTimeoutException as e:
        print(f"Couchbase connection timeout: {e}")
        print("Check if Couchbase server is running and accessible.")
        print(f"Connection string: {CB_SERVER}")
        use_backup_storage = True
        return False
        
    except CouchbaseException as e:
        print(f"Error connecting to Couchbase: {e}")
        use_backup_storage = True
        return False

# Try to connect to Couchbase on startup
connect_to_couchbase()

# Backup storage for when Couchbase is unavailable
def save_to_backup(data, doc_id):
    """Save data to local file as backup when Couchbase is unavailable"""
    backup_dir = os.path.join(os.getcwd(), "backup_data")
    os.makedirs(backup_dir, exist_ok=True)
    
    backup_file = os.path.join(backup_dir, f"{doc_id}.json")
    with open(backup_file, 'w') as f:
        import json
        json.dump(data, f, indent=2)
    
    return backup_file

@app.route('/')
def serve_experiment():
    """Serve the experiment HTML file"""
    return send_from_directory('./', 'experiment.html')

@app.route('/submit-data', methods=['POST'])
def submit_data():
    """Receive and store experiment data in Couchbase"""
    if request.method == 'POST':
        # Get JSON data from request
        data = request.get_json()
        
        if not data:
            return jsonify({"status": "error", "message": "No data provided"}), 400
        
        # Generate a unique ID for this submission
        doc_id = f"experiment:{uuid.uuid4()}"
        
        # Create a wrapper document since jsPsych data is typically an array
        document = {
            "trials": data,  # Store the original array data
            "meta": {
                "timestamp": datetime.datetime.now().isoformat(),
                "document_type": "experiment_result",
                "num_trials": len(data) if isinstance(data, list) else 1
            }
        }
        
        # If we're in backup mode or Couchbase connection fails, use backup storage
        if use_backup_storage:
            try:
                backup_file = save_to_backup(document, doc_id)
                return jsonify({
                    "status": "success", 
                    "message": "Data saved to local backup storage",
                    "id": doc_id,
                    "backup_file": backup_file
                })
            except Exception as e:
                return jsonify({
                    "status": "error", 
                    "message": f"Failed to save data to backup storage: {str(e)}"
                }), 500
        
        # Try to store in Couchbase
        try:
            collection.upsert(doc_id, document)
            
            return jsonify({
                "status": "success", 
                "message": "Data saved successfully to Couchbase",
                "id": doc_id
            })
            
        except CouchbaseException as e:
            # If Couchbase storage fails, try backup storage
            try:
                backup_file = save_to_backup(document, doc_id)
                return jsonify({
                    "status": "warning", 
                    "message": f"Couchbase error: {str(e)}. Data saved to backup storage.",
                    "id": doc_id,
                    "backup_file": backup_file
                })
            except Exception as backup_e:
                return jsonify({
                    "status": "error", 
                    "message": f"Failed to save data: {str(e)}. Backup also failed: {str(backup_e)}"
                }), 500

@app.route('/status', methods=['GET'])
def status():
    """Check the status of the Couchbase connection"""
    if use_backup_storage:
        return jsonify({
            "status": "degraded",
            "message": "Using backup storage (local files). Couchbase connection failed."
        })
    
    try:
        # Simple ping to check if connection is still alive
        ping_result = cluster.ping()
        return jsonify({
            "status": "healthy",
            "message": "Connected to Couchbase",
            "ping": str(ping_result)
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Couchbase connection issue: {str(e)}"
        })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)