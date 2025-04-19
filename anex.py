import api 
from dotenv import load_dotenv
import os
from pymongo import MongoClient
import time
import asyncio
import json
import math
import heapq
load_dotenv()

mongo_uri = os.getenv('MONGO_URI')

api = api.Howdy_API()
client = MongoClient(mongo_uri)
db = client['AggieClassAlert']
collection = db['CRNS']

def find_profs(department, course_code):
    res = api.get_grade_distribution(department, course_code)
    print(f"API returned {len(res)} sections for {department} {course_code}")
    
    # Print a few sample sections to debug
    if res:
        print("Sample section data (first 3 entries):")
        for i, sample in enumerate(res[:3]):
            print(f"  {i+1}. {sample}")
    
    profs = {}
    
    # Create a structure to store regular and honors sections separately
    for c in res:
        prof = c['prof']
        
        if prof not in profs:
            profs[prof] = {
                'regular': [],
                'honors': []
            }
        
        # Check if the section is honors by seeing if the section number starts with 2
        section = c.get('section', '')
        gpa = float(c['gpa'])
        
        # Extract the section number and check if it starts with 2
        # First, strip any extra spaces and remove any text in parentheses
        clean_section = section.strip()
        if '(' in clean_section:
            clean_section = clean_section.split('(')[0].strip()
        print(clean_section)
        # Debug print for each section being processed
        is_honors = clean_section.startswith('2')
        print(f"Section: '{section}' => Clean: '{clean_section}' => Honors: {is_honors}")
        
        # Check if the section number starts with 2
        if int(c['year']) >= 2021:
            if is_honors:
                profs[prof]['honors'].append(gpa)
                print(f"  Added to '{prof}' HONORS: {gpa}")
            else:
                profs[prof]['regular'].append(gpa)
                print(f"  Added to '{prof}' REGULAR: {gpa}")
        print("Section is too old.")
    
    # Calculate average GPAs for regular and honors sections
    averages = {}
    for prof, data in profs.items():
        reg_gpas = data['regular']
        hon_gpas = data['honors']
        print(reg_gpas)
        
        # Calculate average for regular sections if they exist
        reg_avg = sum(reg_gpas) / len(reg_gpas) if reg_gpas else 0
        
        # Calculate average for honors sections if they exist
        hon_avg = sum(hon_gpas) / len(hon_gpas) if hon_gpas else 0
        
        # Calculate overall average
        all_gpas = reg_gpas + hon_gpas
        overall_avg = sum(all_gpas) / len(all_gpas) if all_gpas else 0
        
        averages[prof] = {
            'overall': overall_avg,
            'regular': reg_avg,
            'honors': hon_avg,
            'has_regular': len(reg_gpas) > 0,
            'has_honors': len(hon_gpas) > 0,
            'regular_count': len(reg_gpas),
            'honors_count': len(hon_gpas)
        }
    
    # Print the processed data
    print("\nProcessed professor data:")
    for prof, data in averages.items():
        print(f"  {prof}: Regular: {data['regular_count']} sections, Honors: {data['honors_count']} sections")
    
    # Sort professors by overall GPA and get top 30%
    num_profs = math.floor(len(averages) * 0.3) or 1  # Ensure at least one professor
    top_profs = heapq.nlargest(num_profs, averages.keys(), key=lambda k: averages[k]['overall'])
    
    print("Found professors with GPAs:", averages)
    return averages
    

find_profs('CSCE', '312')