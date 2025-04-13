import asyncio
from api import Howdy_API

def check_instructor_galveston_sections(term, instructor_name):
    api = Howdy_API()
    classes = api.get_classes(term)
    
    # Filter classes for the instructor
    instructor_sections = []
    for class_info in classes:
        print(class_info.get('INSTRUCTOR', ''))
        if instructor_name.lower() in class_info.get('INSTRUCTOR').lower():
            instructor_sections.append(class_info)
    
    print(f"\nFound {len(instructor_sections)} sections for instructor {instructor_name} in term {term}")
    
    # Check each section for Galveston location
    for section in instructor_sections:
        crn = section.get('CRN', 'N/A')
        course = section.get('SUBJECT') + ' ' + section.get('CATALOG_NBR', '')
        section_num = section.get('CLASS_SECTION', 'N/A')
        instructor = section.get('INSTRUCTOR', 'N/A')
        location = section.get('LOCATION', 'N/A')
        
        print(f"\nSection Details:")
        print(f"CRN: {crn}")
        print(f"Course: {course}")
        print(f"Section: {section_num}")
        print(f"Instructor: {instructor}")
        print(f"Location: {location}")

def main():
    instructor_name = input("Enter instructor name to search for: ")
    term = "202531"  # Spring 2025
    check_instructor_galveston_sections(term, instructor_name)

if __name__ == "__main__":
    main() 