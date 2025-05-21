from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import datetime
import os
import uuid
from dotenv import load_dotenv
from couchbase.cluster import Cluster, ClusterOptions
from couchbase.auth import PasswordAuthenticator
from couchbase.exceptions import CouchbaseException

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__, static_folder='./')
CORS(app)  # Enable CORS for all routes

# Get Couchbase configuration from environment variables
CB_USERNAME = os.getenv("CB_USERNAME", "")
CB_PASSWORD = os.getenv("CB_PASSWORD", "")
CB_BUCKET = os.getenv("CB_BUCKET", "")
CB_SERVER = os.getenv("CB_SERVER", "")

# Connect to Couchbase
try:
    auth = PasswordAuthenticator(CB_USERNAME, CB_PASSWORD)
    cluster = Cluster(CB_SERVER, ClusterOptions(auth))
    bucket = cluster.bucket(CB_BUCKET)
    collection = bucket.default_collection()
    print("Successfully connected to Couchbase")
except CouchbaseException as e:
    print(f"Error connecting to Couchbase: {e}")
    # We'll still start the app, but data storage will fail

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
        
        try:
            # Generate a unique ID for this submission
            doc_id = f"experiment:{uuid.uuid4()}"
            
            # Add metadata to the document
            data["meta"] = {
                "timestamp": datetime.datetime.now().isoformat(),
                "document_type": "experiment_result"
            }
            
            # Store data in Couchbase
            collection.upsert(doc_id, data)
            
            return jsonify({
                "status": "success", 
                "message": "Data saved successfully to Couchbase",
                "id": doc_id
            })
            
        except CouchbaseException as e:
            return jsonify({
                "status": "error", 
                "message": f"Failed to save data to Couchbase: {str(e)}"
            }), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)