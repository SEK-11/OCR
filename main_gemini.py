from pdf2image import convert_from_path
import easyocr
import numpy as np
import google.generativeai as genai
import os

def extract_text_from_pdf(pdf_path):
    print("Initializing OCR...")
    reader = easyocr.Reader(['en'], gpu=False)
    pages = convert_from_path(pdf_path)
    
    all_text = []
    for i, img in enumerate(pages):
        print(f"Processing page {i+1}...")
        img_array = np.array(img)
        result = reader.readtext(img_array)
        
        page_text = []
        for item in result:
            text = item[1].strip()
            if len(text) > 1:
                page_text.append(text)
        
        if page_text:
            all_text.extend(page_text)
    
    return "\n".join(all_text)

def setup_gemini_qa(extracted_text, api_key):
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    def answer_question(question):
        prompt = f"""
Based on the following extracted text from a PDF document, please answer the question.

Document content:
{extracted_text}

Question: {question}

Please provide a clear and concise answer based only on the information available in the document. If the information is not available in the document, please say so.
"""
        try:
            response = model.generate_content(prompt)
            return response.text
        except Exception as e:
            return f"Error generating response: {str(e)}"
    
    return answer_question

def main():
    # Get Gemini API key
    api_key = input("Enter your Google Gemini API key: ").strip()
    if not api_key:
        print("API key is required. Get one from: https://makersuite.google.com/app/apikey")
        return
    
    pdf_path = '/home/vmukti/Downloads/ocr/25eab87d-a5fb-46d2-b4ab-35bb1e57d551.pdf'
    
    print("Extracting text from PDF...")
    extracted_text = extract_text_from_pdf(pdf_path)
    
    print(f"Extracted {len(extracted_text)} characters of text")
    print("First 300 characters:")
    print(extracted_text[:300])
    
    if len(extracted_text.strip()) < 10:
        print("Warning: Very little text extracted!")
        return
    
    print("\nSetting up Gemini chatbot...")
    qa_function = setup_gemini_qa(extracted_text, api_key)
    
    print("\nChatbot ready! Ask questions about the PDF content (type 'exit' to quit)")
    print("Example questions:")
    print("- What is the level of spillage detection?")
    print("- What are the OCR recommendations?")
    print("- What are medium priority tasks?")
    
    while True:
        question = input("\nYour question: ").strip()
        if question.lower() in ['exit', 'quit']:
            break
        
        if not question:
            continue
            
        print("Thinking...")
        answer = qa_function(question)
        print(f"\nAnswer: {answer}")

if __name__ == "__main__":
    main()