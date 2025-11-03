from flask import Flask, render_template, jsonify, request
import speech_recognition as sr
import requests
import threading
import time
import uuid
from datetime import datetime
from collections import deque
import json
import os
import re

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'

recognizer = sr.Recognizer()
recognizer.energy_threshold = 300
recognizer.pause_threshold = 0.8
recognizer.dynamic_energy_threshold = True

# LM Studio API configuration
LM_API_URL = "http://localhost:1234/v1/chat/completions"

# Data storage
MEETINGS_FILE = 'meetings.json'

def load_meetings():
    try:
        if os.path.exists(MEETINGS_FILE):
            with open(MEETINGS_FILE, 'r') as f:
                return json.load(f)
    except:
        pass
    return []

def save_meetings(meetings):
    try:
        with open(MEETINGS_FILE, 'w') as f:
            json.dump(meetings[-100:], f, indent=2)
    except Exception as e:
        print(f"Error saving meetings: {e}")

# Active transcription sessions
active_sessions = {}
meetings_history = load_meetings()

def format_conversation(transcript_entries, speaker_count=2):
    """Format transcription entries as a conversation with speakers"""
    conversation = ""
    for i, entry in enumerate(transcript_entries):
        speaker_id = (i % speaker_count) + 1
        conversation += f"Speaker {speaker_id}: {entry['text']}\n\n"
    return conversation.strip()

def extract_title_from_conversation(conversation_text):
    """Extract a meaningful title from the conversation using LLM"""
    headers = {"Content-Type": "application/json"}
    
    prompt = f"""Based on the following conversation, generate a short, descriptive title (max 5-6 words) that captures the main topic or purpose of the discussion. Return ONLY the title without any additional text.

Conversation:
{conversation_text[:500]}  # First 500 characters for context

Title:"""

    payload = {
        "model": "local-model",
        "messages": [
            {
                "role": "system", 
                "content": "You are a helpful assistant that creates concise, descriptive titles for conversations."
            },
            {
                "role": "user", 
                "content": prompt
            }
        ],
        "temperature": 0.3,
        "max_tokens": 50
    }
    
    try:
        response = requests.post(LM_API_URL, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        title = response.json()["choices"][0]["message"]["content"].strip()
        # Clean up the title
        title = re.sub(r'^["\']|["\']$', '', title)  # Remove surrounding quotes
        title = title.split('\n')[0]  # Take only first line
        return title if title else "Team Discussion"
    except Exception as e:
        print(f"Title extraction error: {e}")
        return "Team Discussion"

def summarize_with_lmstudio(conversation_text, meeting_title="Conversation"):
    """Summarize conversation using LM Studio with proper markdown formatting"""
    headers = {"Content-Type": "application/json"}
    
    prompt = f"""Please analyze this meeting conversation and provide a comprehensive summary using proper markdown formatting:

**Meeting:** {meeting_title}

**Conversation:**
{conversation_text}

Please provide a structured summary with the following sections using markdown headers (## for main sections, ### for subsections):

## Meeting Summary
- Brief overview of the main discussion points

## Key Topics Discussed
- List the main topics covered in the conversation

## Decisions Made
- Important decisions or agreements reached

## Action Items
- Specific tasks with responsible persons if mentioned
- Include deadlines if discussed

## Next Steps
- Future plans and follow-up actions

## Important Points
- Notable insights or critical information shared

Format the response using proper markdown with headers, bullet points, and clear organization."""

    payload = {
        "model": "local-model",
        "messages": [
            {
                "role": "system", 
                "content": "You are a professional meeting assistant. Provide clear, structured summaries using markdown formatting with headers (## for main sections), bullet points, and organized sections."
            },
            {
                "role": "user", 
                "content": prompt
            }
        ],
        "temperature": 0.3,
        "max_tokens": 1500
    }
    
    try:
        response = requests.post(LM_API_URL, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        summary = response.json()["choices"][0]["message"]["content"].strip()
        return summary
    except Exception as e:
        return f"## Summary Unavailable\nUnable to generate summary due to: {str(e)}\n\n**Meeting was recorded successfully. You can generate the summary later.**"

def analyze_sentiment_with_lmstudio(conversation_text):
    """Analyze sentiment and dynamics using LM Studio"""
    headers = {"Content-Type": "application/json"}
    
    prompt = f"""Analyze the following conversation and provide insights about:

**Conversation Dynamics**
- Overall tone and sentiment
- Participation balance
- Communication style

**Key Emotional Themes**
- Predominant emotions detected
- Mood shifts if any
- Engagement level

**Interaction Patterns**
- Collaborative or confrontational elements
- Leadership emergence
- Decision-making style

Conversation:
{conversation_text}

Provide the analysis in markdown format with clear sections."""

    payload = {
        "model": "local-model",
        "messages": [
            {
                "role": "system", 
                "content": "You are an expert in conversational analysis. Provide insightful observations using markdown formatting."
            },
            {
                "role": "user", 
                "content": prompt
            }
        ],
        "temperature": 0.3,
        "max_tokens": 800
    }
    
    try:
        response = requests.post(LM_API_URL, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        analysis = response.json()["choices"][0]["message"]["content"].strip()
        return analysis
    except Exception as e:
        return f"## Analysis Unavailable\nUnable to generate analysis due to: {str(e)}"

def continuous_speech_recognition(session_id, language='en-US', speaker_count=2):
    """Continuous speech recognition with conversation formatting"""
    session = active_sessions[session_id]
    
    with sr.Microphone() as source:
        recognizer.adjust_for_ambient_noise(source, duration=1)
        print(f"Starting continuous recognition for session {session_id}")
        
        while session_id in active_sessions and active_sessions[session_id]['active']:
            try:
                audio = recognizer.listen(source, timeout=1, phrase_time_limit=8)
                text = recognizer.recognize_google(audio, language=language)
                
                if text.strip():
                    transcription_entry = {
                        'id': str(uuid.uuid4()),
                        'timestamp': datetime.now().isoformat(),
                        'text': text,
                        'language': language,
                        'session_id': session_id,
                        'type': 'realtime',
                        'speaker': len(session['history']) % speaker_count + 1
                    }
                    
                    session['history'].append(transcription_entry)
                    session['recent_activity'] = datetime.now().isoformat()
                    print(f"Speaker {transcription_entry['speaker']}: {text}")
                    
            except (sr.WaitTimeoutError, sr.UnknownValueError):
                continue
            except Exception as e:
                print(f"Recognition error: {e}")
                time.sleep(0.1)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/start_transcription", methods=["POST"])
def start_transcription():
    try:
        data = request.get_json()
        language = data.get('language', 'en-US')
        speaker_count = int(data.get('speaker_count', 2))
        meeting_title = data.get('meeting_title', 'Team Discussion')
        
        session_id = str(uuid.uuid4())
        active_sessions[session_id] = {
            'id': session_id,
            'language': language,
            'speaker_count': speaker_count,
            'meeting_title': meeting_title,
            'active': True,
            'start_time': datetime.now().isoformat(),
            'recent_activity': datetime.now().isoformat(),
            'history': [],
            'summary': None,
            'analysis': None,
            'summary_generated': False
        }
        
        thread = threading.Thread(
            target=continuous_speech_recognition,
            args=(session_id, language, speaker_count)
        )
        thread.daemon = True
        thread.start()
        
        return jsonify({
            "success": True,
            "session_id": session_id,
            "message": "Meeting recording started"
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/stop_transcription/<session_id>", methods=["POST"])
def stop_transcription(session_id):
    if session_id in active_sessions:
        # Immediately stop the transcription
        active_sessions[session_id]['active'] = False
        time.sleep(0.5)  # Brief pause to ensure recognition stops
        
        session_data = active_sessions[session_id]
        
        # Generate conversation text
        conversation_text = format_conversation(session_data['history'], session_data['speaker_count'])
        
        # Extract meaningful title if default was used
        if session_data['meeting_title'] == 'Team Discussion' and session_data['history']:
            session_data['meeting_title'] = extract_title_from_conversation(conversation_text)
        
        # Create meeting record (without summary initially)
        meeting_record = {
            'id': session_id,
            'title': session_data['meeting_title'],
            'start_time': session_data['start_time'],
            'end_time': datetime.now().isoformat(),
            'duration': len(session_data['history']),
            'speaker_count': session_data['speaker_count'],
            'language': session_data['language'],
            'conversation': conversation_text,
            'summary': None,  # Will be generated later
            'analysis': None, # Will be generated later
            'phrase_count': len(session_data['history']),
            'last_phrase': session_data['history'][-1]['text'] if session_data['history'] else '',
            'summary_generated': False
        }
        
        # Save to history
        meetings_history.append(meeting_record)
        save_meetings(meetings_history)
        
        # Remove from active sessions
        del active_sessions[session_id]
        
        return jsonify({
            "success": True,
            "meeting": meeting_record,
            "message": "Meeting stopped successfully. Generate summary when ready."
        })
    return jsonify({"error": "Session not found"}), 404

@app.route("/api/generate_summary/<meeting_id>", methods=["POST"])
def generate_summary(meeting_id):
    """Generate summary for a specific meeting"""
    try:
        meeting = next((m for m in meetings_history if m['id'] == meeting_id), None)
        if not meeting:
            return jsonify({"error": "Meeting not found"}), 404
        
        # Generate summary and analysis
        summary = summarize_with_lmstudio(meeting['conversation'], meeting['title'])
        analysis = analyze_sentiment_with_lmstudio(meeting['conversation'])
        
        # Update meeting record
        meeting['summary'] = summary
        meeting['analysis'] = analysis
        meeting['summary_generated'] = True
        meeting['summary_generated_at'] = datetime.now().isoformat()
        
        save_meetings(meetings_history)
        
        return jsonify({
            "success": True,
            "summary": summary,
            "analysis": analysis,
            "meeting": meeting
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/meetings")
def get_meetings():
    return jsonify(meetings_history[::-1])

@app.route("/api/meetings/<meeting_id>")
def get_meeting(meeting_id):
    meeting = next((m for m in meetings_history if m['id'] == meeting_id), None)
    if meeting:
        return jsonify(meeting)
    return jsonify({"error": "Meeting not found"}), 404

@app.route("/api/meetings/<meeting_id>", methods=["DELETE"])
def delete_meeting(meeting_id):
    global meetings_history
    meetings_history = [m for m in meetings_history if m['id'] != meeting_id]
    save_meetings(meetings_history)
    return jsonify({"success": True, "message": "Meeting deleted"})

@app.route("/api/transcription_status/<session_id>")
def get_transcription_status(session_id):
    if session_id in active_sessions:
        session = active_sessions[session_id]
        return jsonify({
            "active": session['active'],
            "phrase_count": len(session['history']),
            "recent_activity": session['recent_activity'],
            "history": session['history'][-10:]
        })
    return jsonify({"error": "Session not found"}), 404

@app.route("/api/active_sessions")
def get_active_sessions():
    return jsonify(list(active_sessions.keys()))

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000)