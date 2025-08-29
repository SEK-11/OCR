from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import os
import easyocr
import numpy as np
import google.generativeai as genai
import fitz  # PyMuPDF
from werkzeug.utils import secure_filename
import time
import json
from datetime import datetime
from pdf2image import convert_from_path
from docx import Document
from PIL import Image, ImageEnhance, ImageFilter
import uuid
import hashlib
import cv2

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB max file size
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.secret_key = 'your-secret-key-change-in-production'

# Supported file extensions
SUPPORTED_EXTENSIONS = {'.pdf', '.docx', '.doc', '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff'}

# Create upload directory
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Global storage for user sessions
user_sessions = {}

def get_user_id():
    if 'user_id' not in session:
        session['user_id'] = str(uuid.uuid4())
    return session['user_id']

def get_user_session(user_id):
    if user_id not in user_sessions:
        user_sessions[user_id] = {
            'extracted_text': '',
            'qa_function': None,
            'chat_history': [],
            'document_name': ''
        }
    return user_sessions[user_id]

# Document templates
DOCUMENT_TEMPLATES = {
    'general': [
        'What is the main topic of this document?',
        'Summarize the key points in 3-4 sentences.',
        'What are the important dates mentioned?',
        'Who are the main people or organizations mentioned?'
    ],
    'contract': [
        'What are the parties involved in this contract?',
        'What is the contract duration or term?',
        'What are the key obligations of each party?',
        'What are the payment terms?',
        'What are the termination conditions?'
    ],
    'invoice': [
        'What is the invoice number and date?',
        'Who is the vendor/supplier?',
        'What is the total amount due?',
        'What is the due date for payment?',
        'What items or services are being billed?'
    ],
    'resume': [
        'What is the candidate\'s name and contact information?',
        'What is their current or most recent job title?',
        'What are their key skills and qualifications?',
        'What is their educational background?',
        'How many years of experience do they have?'
    ],
    'research': [
        'What is the main research question or hypothesis?',
        'What methodology was used in this study?',
        'What are the key findings or results?',
        'What are the conclusions and implications?',
        'Who are the authors and what institution are they from?'
    ]
}

def extract_text_from_file(file_path, file_extension):
    try:
        if file_extension == '.pdf':
            return extract_text_from_pdf(file_path)
        elif file_extension in ['.docx', '.doc']:
            return extract_text_from_docx(file_path)
        elif file_extension in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff']:
            return extract_text_from_image(file_path)
        else:
            raise Exception(f"Unsupported file format: {file_extension}")
    except Exception as e:
        print(f"Text extraction error: {str(e)}")
        raise Exception(f"Failed to extract text: {str(e)}")

def preprocess_image_for_ocr(img):
    """Simple and effective image preprocessing for OCR"""
    # Convert PIL to OpenCV format
    img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    
    # Convert to grayscale
    gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
    
    # Simple denoising
    denoised = cv2.fastNlMeansDenoising(gray)
    
    # Convert back to PIL format
    return Image.fromarray(denoised)

def extract_text_from_pdf(pdf_path):
    try:
        doc = fitz.open(pdf_path)
        text_content = ""
        max_pages = min(5, len(doc))
        for page_num in range(max_pages):
            page = doc.load_page(page_num)
            text_content += page.get_text()
        doc.close()
        
        if len(text_content.strip()) > 100:
            print(f"Extracted {len(text_content)} characters using PyMuPDF")
            return text_content
        
        # OCR for image-based PDFs
        print("Using OCR for image-based PDF...")
        reader = easyocr.Reader(['en'], gpu=False)
        
        # Convert pages with good quality
        pages = convert_from_path(pdf_path, dpi=200, first_page=1, last_page=10)
        
        all_text = []
        for i, img in enumerate(pages):
            print(f"Processing page {i+1}/{len(pages)} with OCR...")
            
            # Apply simple preprocessing
            processed_img = preprocess_image_for_ocr(img)
            
            # OCR with standard settings
            result = reader.readtext(
                np.array(processed_img), 
                detail=0,
                paragraph=True,
                width_ths=0.7,
                height_ths=0.7
            )
            
            page_text = []
            for text in result:
                cleaned_text = text.strip()
                if len(cleaned_text) > 1:  # Keep more text
                    page_text.append(cleaned_text)
            
            if page_text:
                all_text.extend(page_text)
        
        extracted_text = "\n".join(all_text)
        print(f"OCR complete. Extracted {len(extracted_text)} characters")
        return extracted_text
        
    except Exception as e:
        raise Exception(f"PDF extraction failed: {str(e)}")

def extract_text_from_docx(docx_path):
    try:
        doc = Document(docx_path)
        text_content = "\n".join([paragraph.text for paragraph in doc.paragraphs])
        print(f"Extracted {len(text_content)} characters from DOCX")
        return text_content
    except Exception as e:
        raise Exception(f"DOCX extraction failed: {str(e)}")

def extract_text_from_image(image_path):
    try:
        reader = easyocr.Reader(['en'], gpu=False)
        img = Image.open(image_path)
        
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Keep original size or resize moderately
        if img.width > 3000:
            ratio = 3000 / img.width
            new_height = int(img.height * ratio)
            img = img.resize((3000, new_height), Image.LANCZOS)
        
        # Apply preprocessing for better OCR
        processed_img = preprocess_image_for_ocr(img)
        
        # OCR with standard settings
        result = reader.readtext(
            np.array(processed_img), 
            detail=0,
            paragraph=True,
            width_ths=0.7,
            height_ths=0.7
        )
        
        text_content = "\n".join([text.strip() for text in result if len(text.strip()) > 1])
        print(f"Extracted {len(text_content)} characters from image with OCR")
        return text_content
    except Exception as e:
        raise Exception(f"Image extraction failed: {str(e)}")

def setup_gemini_qa(extracted_text, api_key):
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    def answer_question(question):
        prompt = f"""Based on the following extracted text from a document, please answer the question in a clear and well-formatted manner.

Document content:
{extracted_text}

Question: {question}

Instructions:
- Provide a clear, well-structured answer
- Use proper paragraphs and line breaks for readability
- Present numerical data in a clean format
- If listing multiple items, use bullet points or numbered lists
- Keep the response concise but complete
- Only use information from the document provided

Answer:"""
        
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
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file selected'}), 400
        
        file = request.files['file']
        api_key = request.form.get('api_key')
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not api_key:
            return jsonify({'error': 'API key is required'}), 400
        
        # Check file extension
        file_extension = os.path.splitext(file.filename.lower())[1]
        if file_extension not in SUPPORTED_EXTENSIONS:
            return jsonify({'error': f'Unsupported file format. Supported: {list(SUPPORTED_EXTENSIONS)}'}), 400
        
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        try:
            user_id = get_user_id()
            user_session = get_user_session(user_id)
            
            print(f"Starting text extraction for {file_extension} file...")
            extracted_text = extract_text_from_file(filepath, file_extension)
            
            if len(extracted_text.strip()) < 5:
                return jsonify({'error': 'Could not extract text from file. Please ensure it contains readable content.'}), 422
            
            print(f"Extracted {len(extracted_text)} characters")
            
            # Store in user session
            user_session['extracted_text'] = extracted_text
            user_session['qa_function'] = setup_gemini_qa(extracted_text, api_key)
            user_session['document_name'] = filename
            user_session['chat_history'] = []  # Reset chat history for new document
            
            return jsonify({
                'success': True,
                'text_length': len(extracted_text),
                'preview': extracted_text[:300],
                'filename': filename,
                'file_type': file_extension
            })
            
        except Exception as e:
            print(f"Processing error: {str(e)}")
            return jsonify({'error': f'Processing failed: {str(e)}'}), 500
        finally:
            if os.path.exists(filepath):
                os.remove(filepath)
    
    except Exception as e:
        print(f"Upload error: {str(e)}")
        return jsonify({'error': f'Upload failed: {str(e)}'}), 500

@app.route('/ask', methods=['POST'])
def ask_question():
    try:
        user_id = get_user_id()
        user_session = get_user_session(user_id)
        
        if user_session['qa_function'] is None:
            return jsonify({'error': 'Please upload and process a document first'}), 400
        
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid JSON data'}), 400
            
        question = data.get('question')
        if not question or not question.strip():
            return jsonify({'error': 'Question is required'}), 400
        
        answer = user_session['qa_function'](question.strip())
        
        chat_entry = {
            'id': str(uuid.uuid4()),
            'question': question.strip(),
            'answer': answer,
            'timestamp': datetime.now().isoformat()
        }
        user_session['chat_history'].append(chat_entry)
        
        return jsonify({
            'success': True,
            'answer': answer,
            'message': chat_entry,
            'chat_history': user_session['chat_history']
        })
    except Exception as e:
        print(f"Question processing error: {str(e)}")
        return jsonify({'error': f'Error generating answer: {str(e)}'}), 500

@app.route('/templates')
def get_templates():
    return jsonify(DOCUMENT_TEMPLATES)

@app.route('/chat-history')
def get_chat_history():
    user_id = get_user_id()
    user_session = get_user_session(user_id)
    return jsonify({
        'chat_history': user_session['chat_history'],
        'document_name': user_session['document_name']
    })

@app.route('/history')
def get_history():
    user_id = get_user_id()
    user_session = get_user_session(user_id)
    return jsonify(user_session['chat_history'])

@app.route('/clear-history', methods=['POST'])
def clear_chat_history():
    user_id = get_user_id()
    user_session = get_user_session(user_id)
    user_session['chat_history'] = []
    return jsonify({'success': True})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)