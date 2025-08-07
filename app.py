from flask import Flask, render_template, request, jsonify, redirect, url_for
import os
import easyocr
import numpy as np
import google.generativeai as genai
import fitz  # PyMuPDF
from werkzeug.utils import secure_filename
import time

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max file size

# Create upload directory
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Global variables to store extracted text and QA function
extracted_text = ""
qa_function = None

def extract_text_from_pdf(pdf_path):
    print("Extracting text using PyMuPDF...")
    doc = fitz.open(pdf_path)
    all_text = []
    for page_num, page in enumerate(doc):
        print(f"Processing page {page_num + 1}...")
        text = page.get_text("text")  # Plain text extraction
        all_text.append(text)
    return "\n".join(all_text)

def setup_gemini_qa(extracted_text, api_key):
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    def answer_question(question):
        prompt = f"""Based on the following extracted text from a PDF document, please answer the question.

Document content:
{extracted_text}

Question: {question}

Please provide a clear and concise answer based only on the information available in the document."""
        
        try:
            response = model.generate_content(prompt)
            return response.text
        except Exception as e:
            return f"Error: {str(e)}"
    
    return answer_question

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    global extracted_text, qa_function
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file selected'})
    
    file = request.files['file']
    api_key = request.form.get('api_key')
    
    if file.filename == '':
        return jsonify({'error': 'No file selected'})
    
    if not api_key:
        return jsonify({'error': 'API key is required'})
    
    if file and file.filename.lower().endswith('.pdf'):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        try:
            # Extract text
            print("Starting text extraction...")
            extracted_text = extract_text_from_pdf(filepath)
            
            if len(extracted_text.strip()) < 10:
                return jsonify({'error': 'Very little text extracted from PDF'})
            
            # Setup QA
            qa_function = setup_gemini_qa(extracted_text, api_key)
            
            # Clean up uploaded file
            os.remove(filepath)
            
            return jsonify({
                'success': True,
                'text_length': len(extracted_text),
                'preview': extracted_text[:500]
            })
            
        except Exception as e:
            return jsonify({'error': f'Processing failed: {str(e)}'})
    
    return jsonify({'error': 'Please upload a PDF file'})

@app.route('/ask', methods=['POST'])
def ask_question():
    global qa_function
    
    if qa_function is None:
        return jsonify({'error': 'Please upload and process a PDF first'})
    
    question = request.json.get('question')
    if not question:
        return jsonify({'error': 'Question is required'})
    
    try:
        answer = qa_function(question)
        return jsonify({'answer': answer})
    except Exception as e:
        return jsonify({'error': f'Error generating answer: {str(e)}'})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)