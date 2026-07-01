#!/usr/bin/env python3
"""
E-ink Display Web Configuration Panel
A simple web interface to manage .env configuration without SSH
"""

import os
import sys
from flask import Flask, render_template_string, request, redirect, url_for, flash, jsonify
from werkzeug.security import check_password_hash, generate_password_hash
from dotenv import load_dotenv, set_key, unset_key
import json
from datetime import datetime
import subprocess

# Load environment variables 
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

app = Flask(__name__)
app.secret_key = os.getenv('WEB_CONFIG_SECRET_KEY', 'BusAuntieSK')

# Configuration
WEB_CONFIG_PORT = int(os.getenv('WEB_CONFIG_PORT', '5000'))
WEB_CONFIG_HOST = os.getenv('WEB_CONFIG_HOST', '0.0.0.0')
WEB_CONFIG_USERNAME = os.getenv('WEB_CONFIG_USERNAME', 'admin')
WEB_CONFIG_PASSWORD_HASH = os.getenv('WEB_CONFIG_PASSWORD_HASH', 
                                      generate_password_hash('admin123'))  # Default password

ENV_FILE = os.path.join(os.path.dirname(__file__), '.env')

# Configuration categories and their variables
CONFIG_SCHEMA = {
'Core Settings': {
    'API_KEY': {'type': 'password', 'label': 'LTA DataMall API Key', 'required': True},
    'BUS_STOP_CODE_A': {'type': 'text', 'label': 'Bus Stop Code', 'required': True},
    'A_HEADER': {'type': 'text', 'label': 'Bus Stop Display Name', 'required': False},
    'API_BUS_URL': {'type': 'text', 'label': 'Bus Arrival API URL', 'required': False, 'default': 'http://datamall2.mytransport.sg/ltaodataservice/BusArrivalv2?BusStopCode='},
    'API_TRAIN_URL': {'type': 'text', 'label': 'Train Service Alerts API URL', 'required': False, 'default': 'http://datamall2.mytransport.sg/ltaodataservice/TrainServiceAlerts'},
    'API_BUS_STOP_INFO_URL': {'type': 'text', 'label': 'Bus Stop Info API URL', 'required': False, 'default': 'https://datamall2.mytransport.sg/ltaodataservice/BusStops?BusStopCode='},
    'LOG_LEVEL': {'type': 'select', 'label': 'Log Level', 'options': ['DEBUG', 'INFO', 'WARNING', 'ERROR'], 'required': False},
},
    'Journey Time Settings': {
        'SHOW_JOURNEY_TIME': {'type': 'checkbox', 'label': 'Enable Journey Time Tracking', 'required': False},
        'BUS_SERVICES_TO_TRACK': {'type': 'text', 'label': 'Bus Services to Track (comma-separated)', 'required': False, 'placeholder': '67,969,75'},
        'JOURNEY_DESTINATION': {'type': 'text', 'label': 'Journey Destination', 'required': False, 'placeholder': 'School Name, Singapore'},
        'JOURNEY_DESTINATION_SHORT': {'type': 'text', 'label': 'Short Display Name (optional)', 'required': False, 'placeholder': 'School'},
        'ROUTING_API_PROVIDER': {'type': 'select', 'label': 'Routing API Provider', 'options': ['onemap', 'google'], 'required': False},
        'GOOGLE_MAPS_API_KEY': {'type': 'password', 'label': 'Google Maps API Key', 'required': False},
        'ONEMAP_API_KEY': {'type': 'password', 'label': 'OneMap API Key (optional)', 'required': False},
        'JOURNEY_TIME_CACHE_DURATION': {'type': 'number', 'label': 'Journey Cache Duration (seconds)', 'required': False, 'default': '1800'},
    },
    'Schedule Settings': {
        'WAKE_HOUR': {'type': 'number', 'label': 'Wake Hour (24hr format)', 'required': False, 'default': '7', 'min': '0', 'max': '23'},
        'SLEEP_HOUR': {'type': 'number', 'label': 'Sleep Hour (24hr format)', 'required': False, 'default': '22', 'min': '0', 'max': '23'},
        'WAKE_INTERVAL': {'type': 'number', 'label': 'Wake Update Interval (seconds)', 'required': False, 'default': '30'},
        'SLEEP_INTERVAL': {'type': 'number', 'label': 'Sleep Update Interval (seconds)', 'required': False, 'default': '300'},
        'DEBUG_SKIP_TIME_CHECK': {'type': 'checkbox', 'label': 'Debug Mode (Always Awake)', 'required': False},
    },
    'Home Assistant': {
        'HOME_ASSISTANT_API_URL': {'type': 'text', 'label': 'Home Assistant API URL', 'required': False, 'placeholder': 'http://homeassistant.local:8123'},
        'HOME_ASSISTANT_TOKEN': {'type': 'password', 'label': 'Home Assistant Long-Lived Token', 'required': False},
        'HOME_ASSISTANT_WEATHER_ENTITY': {'type': 'text', 'label': 'Weather Entity ID', 'required': False, 'default': 'weather.home'},
        'HOME_ASSISTANT_SLEEP_URL': {'type': 'text', 'label': 'Sleep Screen URL', 'required': False},
        'WEATHER_CACHE_DURATION': {'type': 'number', 'label': 'Weather Cache Duration (seconds)', 'required': False, 'default': '1800'},
    },
    'MQTT Settings': {
        'MQTT_ENABLED': {'type': 'checkbox', 'label': 'Enable MQTT', 'required': False},
        'MQTT_BROKER': {'type': 'text', 'label': 'MQTT Broker Address', 'required': False, 'default': 'localhost'},
        'MQTT_PORT': {'type': 'number', 'label': 'MQTT Port', 'required': False, 'default': '1883'},
        'MQTT_USERNAME': {'type': 'text', 'label': 'MQTT Username', 'required': False},
        'MQTT_PASSWORD': {'type': 'password', 'label': 'MQTT Password', 'required': False},
        'MQTT_TOPIC_REFRESH': {'type': 'text', 'label': 'Refresh Topic', 'required': False, 'default': 'eink/display/refresh'},
        'MQTT_TOPIC_STATUS': {'type': 'text', 'label': 'Status Topic', 'required': False, 'default': 'eink/display/status'},
    },
}

# HTML Template
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>E-ink Display Configuration</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1000px;
            margin: 0 auto;
        }
        
        .header {
            background: white;
            padding: 30px;
            border-radius: 12px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }
        
        .header h1 {
            color: #333;
            font-size: 28px;
            margin-bottom: 10px;
        }
        
        .header p {
            color: #666;
            font-size: 14px;
        }
        
        .status-bar {
            background: white;
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            margin-bottom: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .status-item {
            text-align: center;
        }
        
        .status-label {
            font-size: 12px;
            color: #666;
            margin-bottom: 5px;
        }
        
        .status-value {
            font-size: 18px;
            font-weight: bold;
            color: #333;
        }
        
        .card {
            background: white;
            padding: 30px;
            border-radius: 12px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }
        
        .card h2 {
            color: #333;
            font-size: 20px;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid #667eea;
        }
        
        .form-group {
            margin-bottom: 20px;
        }
        
        .form-group label {
            display: block;
            margin-bottom: 8px;
            color: #333;
            font-weight: 500;
            font-size: 14px;
        }
        
        .form-group input[type="text"],
        .form-group input[type="password"],
        .form-group input[type="number"],
        .form-group select {
            width: 100%;
            padding: 12px;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            font-size: 14px;
            transition: border-color 0.3s;
        }
        
        .form-group input:focus,
        .form-group select:focus {
            outline: none;
            border-color: #667eea;
        }
        
        .form-group input[type="checkbox"] {
            width: 20px;
            height: 20px;
            cursor: pointer;
        }
        
        .checkbox-wrapper {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .btn {
            padding: 12px 24px;
            border: none;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
        }
        
        .btn-primary {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }
        
        .btn-primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 12px rgba(102, 126, 234, 0.4);
        }
        
        .btn-secondary {
            background: #f0f0f0;
            color: #333;
        }
        
        .btn-secondary:hover {
            background: #e0e0e0;
        }
        
        .btn-danger {
            background: #ef4444;
            color: white;
        }
        
        .btn-danger:hover {
            background: #dc2626;
        }
        
        .actions {
            display: flex;
            gap: 10px;
            justify-content: flex-end;
            margin-top: 30px;
        }
        
        .alert {
            padding: 15px 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            font-size: 14px;
        }
        
        .alert-success {
            background: #d1fae5;
            color: #065f46;
            border: 1px solid #a7f3d0;
        }
        
        .alert-error {
            background: #fee2e2;
            color: #991b1b;
            border: 1px solid #fecaca;
        }
        
        .alert-info {
            background: #dbeafe;
            color: #1e40af;
            border: 1px solid #bfdbfe;
        }
        
        .helper-text {
            font-size: 12px;
            color: #666;
            margin-top: 5px;
        }
        
        .required {
            color: #ef4444;
        }
        
        @media (max-width: 768px) {
            .status-bar {
                flex-direction: column;
                gap: 15px;
            }
            
            .actions {
                flex-direction: column;
            }
            
            .btn {
                width: 100%;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        {% if not logged_in %}
        <!-- Login Form -->
        <div class="header">
            <h1>🔐 E-ink Display Configuration</h1>
            <p>Please log in to continue</p>
        </div>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        <div class="card">
            <form method="POST" action="{{ url_for('login') }}">
                <div class="form-group">
                    <label for="username">Username</label>
                    <input type="text" id="username" name="username" required>
                </div>
                
                <div class="form-group">
                    <label for="password">Password</label>
                    <input type="password" id="password" name="password" required>
                </div>
                
                <div class="actions">
                    <button type="submit" class="btn btn-primary">Login</button>
                </div>
            </form>
        </div>
        
        {% else %}
        <!-- Main Configuration Interface -->
        <div class="header">
            <h1>🖥️ E-ink Display Configuration</h1>
            <p>Manage your e-ink display settings</p>
        </div>
        
        <div class="status-bar">
            <div class="status-item">
                <div class="status-label">Configuration</div>
                <div class="status-value" style="color: #10b981;">✓ Loaded</div>
            </div>
            <div class="status-item">
                <div class="status-label">Last Updated</div>
                <div class="status-value">{{ last_updated }}</div>
            </div>
            <div class="status-item">
                <button onclick="triggerRefresh()" class="btn btn-secondary">🔄 Refresh Display</button>
            </div>
            <div class="status-item">
                <a href="{{ url_for('logout') }}" class="btn btn-secondary">Logout</a>
            </div>
        </div>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        <form method="POST" action="{{ url_for('save_config') }}">
            {% for category, fields in config_schema.items() %}
            <div class="card">
                <h2>{{ category }}</h2>
                
                {% for field_name, field_config in fields.items() %}
                <div class="form-group">
                    <label for="{{ field_name }}">
                        {{ field_config.label }}
                        {% if field_config.required %}<span class="required">*</span>{% endif %}
                    </label>
                    
                    {% if field_config.type == 'text' or field_config.type == 'password' %}
                        <input 
                            type="{{ field_config.type }}" 
                            id="{{ field_name }}" 
                            name="{{ field_name }}"
                            value="{{ config.get(field_name, field_config.get('default', '')) }}"
                            placeholder="{{ field_config.get('placeholder', '') }}"
                            {% if field_config.required %}required{% endif %}
                        >
                    {% elif field_config.type == 'number' %}
                        <input 
                            type="number" 
                            id="{{ field_name }}" 
                            name="{{ field_name }}"
                            value="{{ config.get(field_name, field_config.get('default', '')) }}"
                            {% if field_config.get('min') %}min="{{ field_config.min }}"{% endif %}
                            {% if field_config.get('max') %}max="{{ field_config.max }}"{% endif %}
                            {% if field_config.required %}required{% endif %}
                        >
                    {% elif field_config.type == 'select' %}
                        <select id="{{ field_name }}" name="{{ field_name }}" {% if field_config.required %}required{% endif %}>
                            <option value="">-- Select --</option>
                            {% for option in field_config.options %}
                                <option value="{{ option }}" {% if config.get(field_name) == option %}selected{% endif %}>
                                    {{ option }}
                                </option>
                            {% endfor %}
                        </select>
                    {% elif field_config.type == 'checkbox' %}
                        <div class="checkbox-wrapper">
                            <input 
                                type="checkbox" 
                                id="{{ field_name }}" 
                                name="{{ field_name }}"
                                value="true"
                                {% if config.get(field_name, '').lower() == 'true' %}checked{% endif %}
                            >
                            <label for="{{ field_name }}" style="margin: 0;">Enable</label>
                        </div>
                    {% endif %}
                    
                    {% if field_config.get('placeholder') %}
                        <div class="helper-text">Example: {{ field_config.placeholder }}</div>
                    {% endif %}
                </div>
                {% endfor %}
            </div>
            {% endfor %}
            
            <div class="actions">
                <button type="button" onclick="location.reload()" class="btn btn-secondary">Cancel</button>
                <button type="submit" class="btn btn-primary">💾 Save Configuration</button>
            </div>
        </form>
        {% endif %}
    </div>
    
    <script>
        function triggerRefresh() {
            fetch('/api/refresh', { method: 'POST' })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        alert('✓ Display refresh triggered!');
                    } else {
                        alert('✗ Failed to trigger refresh: ' + data.error);
                    }
                })
                .catch(error => {
                    alert('✗ Error: ' + error);
                });
        }
    </script>
</body>
</html>
'''

def read_env_file():
    """Read current .env file configuration"""
    config = {}
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    config[key.strip()] = value.strip()
    return config

def write_env_file(config):
    """Write configuration to .env file"""
    for key, value in config.items():
        if value:
            set_key(ENV_FILE, key, value)
        else:
            unset_key(ENV_FILE, key)

def check_auth(username, password):
    """Check if username/password combination is valid"""
    return username == WEB_CONFIG_USERNAME and check_password_hash(WEB_CONFIG_PASSWORD_HASH, password)

@app.route('/')
def index():
    """Main configuration page"""
    logged_in = request.cookies.get('logged_in') == 'true'
    
    if not logged_in:
        return render_template_string(HTML_TEMPLATE, 
                                     logged_in=False)
    
    config = read_env_file()
    last_updated = datetime.fromtimestamp(os.path.getmtime(ENV_FILE)).strftime('%Y-%m-%d %H:%M') if os.path.exists(ENV_FILE) else 'Never'
    
    return render_template_string(HTML_TEMPLATE, 
                                 logged_in=True,
                                 config=config,
                                 config_schema=CONFIG_SCHEMA,
                                 last_updated=last_updated)

@app.route('/login', methods=['POST'])
def login():
    """Handle login"""
    username = request.form.get('username')
    password = request.form.get('password')
    
    if check_auth(username, password):
        response = redirect(url_for('index'))
        response.set_cookie('logged_in', 'true', max_age=3600*8)  # 8 hours
        flash('Successfully logged in!', 'success')
        return response
    else:
        flash('Invalid username or password', 'error')
        return redirect(url_for('index'))

@app.route('/logout')
def logout():
    """Handle logout"""
    response = redirect(url_for('index'))
    response.set_cookie('logged_in', '', expires=0)
    flash('Successfully logged out', 'info')
    return response

@app.route('/save', methods=['POST'])
def save_config():
    """Save configuration"""
    if request.cookies.get('logged_in') != 'true':
        return redirect(url_for('index'))
    
    # Read form data
    new_config = {}
    for category, fields in CONFIG_SCHEMA.items():
        for field_name, field_config in fields.items():
            if field_config['type'] == 'checkbox':
                new_config[field_name] = 'true' if request.form.get(field_name) == 'true' else 'false'
            else:
                value = request.form.get(field_name, '').strip()
                if value:
                    new_config[field_name] = value
    
    # Write to .env file
    try:
        write_env_file(new_config)
        flash('Configuration saved successfully! Restart the display service to apply changes.', 'success')
    except Exception as e:
        flash(f'Error saving configuration: {str(e)}', 'error')
    
    return redirect(url_for('index'))

@app.route('/api/refresh', methods=['POST'])
def api_refresh():
    """Trigger manual display refresh via MQTT"""
    if request.cookies.get('logged_in') != 'true':
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401
    
    try:
        # Try to publish MQTT message
        import paho.mqtt.publish as publish
        
        mqtt_broker = os.getenv('MQTT_BROKER', 'localhost')
        mqtt_port = int(os.getenv('MQTT_PORT', '1883'))
        mqtt_topic = os.getenv('MQTT_TOPIC_REFRESH', 'eink/display/refresh')
        
        auth = None
        if os.getenv('MQTT_USERNAME') and os.getenv('MQTT_PASSWORD'):
            auth = {'username': os.getenv('MQTT_USERNAME'), 'password': os.getenv('MQTT_PASSWORD')}
        
        publish.single(mqtt_topic, 'refresh', hostname=mqtt_broker, port=mqtt_port, auth=auth)
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/status')
def api_status():
    """Get system status"""
    if request.cookies.get('logged_in') != 'true':
        return jsonify({'error': 'Not authenticated'}), 401
    
    return jsonify({
        'config_exists': os.path.exists(ENV_FILE),
        'last_modified': datetime.fromtimestamp(os.path.getmtime(ENV_FILE)).isoformat() if os.path.exists(ENV_FILE) else None
    })

if __name__ == '__main__':
    print("=" * 60)
    print("E-ink Display Web Configuration Panel")
    print("=" * 60)
    print(f"\n🌐 Access at: http://{WEB_CONFIG_HOST}:{WEB_CONFIG_PORT}")
    print(f"👤 Default username: {WEB_CONFIG_USERNAME}")
    print(f"🔑 Default password: admin123")
    print("\n⚠️  IMPORTANT: Change the default password in .env!")
    print("   Add: WEB_CONFIG_PASSWORD_HASH=<your_hash>")
    print("\n   Generate hash with:")
    print("   python3 -c \"from werkzeug.security import generate_password_hash; print(generate_password_hash('your_password'))\"")
    print("\n" + "=" * 60 + "\n")
    
    app.run(host=WEB_CONFIG_HOST, port=WEB_CONFIG_PORT, debug=False)