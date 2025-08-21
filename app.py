from flask import Flask, render_template, request, jsonify, redirect, url_for
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

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB max file size
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

# Create upload directory
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Global variables to store extracted text and QA function
extracted_text = ""
qa_function = None
chat_history = []

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

def extract_text_from_pdf(pdf_path):
    try:
        # Try PyMuPDF first (faster for text-based PDFs)
        doc = fitz.open(pdf_path)
        text_content = ""
        
        # Extract text from first 5 pages only
        max_pages = min(5, len(doc))
        for page_num in range(max_pages):
            page = doc.load_page(page_num)
            text_content += page.get_text()
        
        doc.close()
        
        # If we got substantial text, return it
        if len(text_content.strip()) > 100:
            print(f"Extracted {len(text_content)} characters using PyMuPDF")
            return text_content
        
        # Fallback to OCR for image-based PDFs (limited processing)
        print("Text extraction minimal, trying OCR...")
        reader = easyocr.Reader(['en'], gpu=False)
        
        # Convert only first 2 pages at lower DPI for speed
        pages = convert_from_path(pdf_path, dpi=150, first_page=1, last_page=2)
        
        if not pages:
            raise Exception("Could not convert PDF to images")
        
        all_text = []
        for i, img in enumerate(pages):
            print(f"OCR processing page {i+1}/{len(pages)}...")
            # Resize image for faster processing
            img = img.resize((img.width//2, img.height//2))
            img_array = np.array(img)
            result = reader.readtext(img_array, detail=0, width_ths=0.9, height_ths=0.9)
            
            for text in result:
                text = text.strip()
                if len(text) > 1:
                    all_text.append(text)
        
        extracted_text = "\n".join(all_text)
        print(f"OCR extraction complete. Total text length: {len(extracted_text)}")
        return extracted_text
        
    except Exception as e:
        print(f"Text extraction error: {str(e)}")
        raise Exception(f"Failed to extract text from PDF: {str(e)}")

def setup_gemini_qa(extracted_text, api_key):
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    def answer_question(question):
        prompt = f"""Based on the following extracted text from a PDF document, please answer the question in a clear and well-formatted manner.

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
    global extracted_text, qa_function
    
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file selected'}), 400
        
        file = request.files['file']
        api_key = request.form.get('api_key')
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not api_key:
            return jsonify({'error': 'API key is required'}), 400
        
        if not file.filename.lower().endswith('.pdf'):
            return jsonify({'error': 'Please upload a PDF file'}), 400
        
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        try:
            # Extract text
            print("Starting text extraction...")
            extracted_text = extract_text_from_pdf(filepath)
            
            if len(extracted_text.strip()) < 5:
                return jsonify({'error': 'Could not extract text from PDF. Please ensure the PDF contains readable text or images.'}), 422
            
            print(f"Extracted {len(extracted_text)} characters from PDF")
            
            # Setup QA
            qa_function = setup_gemini_qa(extracted_text, api_key)
            
            return jsonify({
                'success': True,
                'text_length': len(extracted_text),
                'preview': extracted_text[:500],
                'filename': filename
            })
            
        except Exception as e:
            print(f"Processing error: {str(e)}")
            return jsonify({'error': f'Processing failed: {str(e)}'}), 500
        finally:
            # Always clean up uploaded file
            if os.path.exists(filepath):
                os.remove(filepath)
    
    except Exception as e:
        print(f"Upload error: {str(e)}")
        return jsonify({'error': f'Upload failed: {str(e)}'}), 500

@app.route('/ask', methods=['POST'])
def ask_question():
    global qa_function, chat_history
    
    try:
        if qa_function is None:
            return jsonify({'error': 'Please upload and process a PDF first'}), 400
        
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid JSON data'}), 400
            
        question = data.get('question')
        if not question or not question.strip():
            return jsonify({'error': 'Question is required'}), 400
        
        answer = qa_function(question.strip())
        
        # Add to chat history
        chat_entry = {
            'question': question.strip(),
            'answer': answer,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        chat_history.append(chat_entry)
        
        return jsonify({
            'answer': answer,
            'chat_history': chat_history
        })
    except Exception as e:
        print(f"Question processing error: {str(e)}")
        return jsonify({'error': f'Error generating answer: {str(e)}'}), 500

@app.route('/templates')
def get_templates():
    return jsonify(DOCUMENT_TEMPLATES)

@app.route('/chat-history')
def get_chat_history():
    return jsonify(chat_history)

@app.route('/clear-history', methods=['POST'])
def clear_chat_history():
    global chat_history
    chat_history = []
    return jsonify({'success': True})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)