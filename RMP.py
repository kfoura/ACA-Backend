import requests
from bs4 import BeautifulSoup

# Function to get professor ratings from Rate My Professors
def get_professor_rating(prof_last_name, department):
    """
    Get rating information for a professor from RateMyProfessors.com
    
    Args:
        prof_last_name (str): The last name of the professor to search for
        department (str): The department name (e.g., "Computer Science")
        
    Returns:
        dict: A dictionary containing overall_rating, would_take_again, difficulty, and comments
              If professor not found, all values will be None and found will be False
    """
    print(f"Searching for RateMyProfessor data: {prof_last_name} in department {department}")
    
    # Define result structure with default values
    result = {
        "overall_rating": None,
        "would_take_again": None, 
        "difficulty": None,
        "comments": {},
        "found": False
    }
    
    try:
        # Set up headers to mimic a browser request
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
            "Referer": "https://www.ratemyprofessors.com/",
        }
        
        # Create a session for making requests
        session = requests.Session()
        session.headers.update(headers)
        
        # Search for the professor by last name
        search_url = f"https://www.ratemyprofessors.com/search/professors/1003?q={prof_last_name}"
        print(f"Searching URL: {search_url}")
        
        response = requests.get(search_url, headers=headers)
        
        if response.status_code != 200:
            print(f"Error searching for professor {prof_last_name}: HTTP {response.status_code}")
            return result
            
        print(f"Search successful - HTTP {response.status_code}")
        
        # Parse the search results
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Find professor cards that match the department
        prof_cards = soup.find_all("div", class_="CardSchool__Department-sc-19lmz2k-0")
        print(f"Found {len(prof_cards)} professor cards on search page")
        
        # Find the card that matches our department
        matching_card = None
        for div in prof_cards:
            print(f"Checking department: '{div.text}' against '{department}'")
            # Convert TAMU department codes to text names for matching
            if department_matches(div.text, department):
                # Found a matching department
                matching_card = div
                print(f"MATCH FOUND: '{div.text}' matches '{department}'")
                break
        
        if not matching_card:
            print(f"No professor found with last name '{prof_last_name}' in department '{department}'")
            return result
        
        # Get the professor link from the card's parent
        link_element = matching_card.find_parent("a", class_="TeacherCard__StyledTeacherCard-syjs0d-0")
        if not link_element:
            print(f"Could not find link for professor {prof_last_name}")
            return result
        
        prof_link = link_element.get("href")
        if not prof_link:
            print(f"No link found for professor {prof_last_name}")
            return result
        
        # Visit the professor's page
        prof_url = f"https://www.ratemyprofessors.com{prof_link}"
        print(f"Visiting professor page: {prof_url}")
        
        prof_response = requests.get(prof_url, headers=headers)
        
        if prof_response.status_code != 200:
            print(f"Error accessing professor page: HTTP {prof_response.status_code}")
            return result
            
        print(f"Professor page loaded successfully - HTTP {prof_response.status_code}")
        
        # Parse the professor's page
        prof_soup = BeautifulSoup(prof_response.text, "html.parser")
        
        # Extract overall rating
        rating_div = prof_soup.find("div", class_="RatingValue__Numerator-qw8sqy-2")
        if rating_div:
            result["overall_rating"] = rating_div.text.strip()
            print(f"Found overall rating: {result['overall_rating']}")
        
        # Extract "would take again" percentage
        feedback_divs = prof_soup.find_all("div", class_="FeedbackItem__FeedbackNumber-uof32n-1")
        if feedback_divs and len(feedback_divs) > 0:
            result["would_take_again"] = feedback_divs[0].text.strip()
            print(f"Found would take again: {result['would_take_again']}")
        
        # Extract difficulty rating
        if feedback_divs and len(feedback_divs) > 1:
            result["difficulty"] = feedback_divs[1].text.strip()
            print(f"Found difficulty: {result['difficulty']}")
        
        # Extract common tags/comments
        tags = prof_soup.find_all("span", class_="Tag-bs9vf4-0")
        if tags:
            result["comments"] = {tag.text.strip(): 0 for tag in tags}
            print(f"Found {len(tags)} tags/comments")
        
        # Mark as found if we extracted the overall rating
        result["found"] = result["overall_rating"] is not None
        print(f"RMP data found: {result['found']}")
        
        print(f"Final RMP result for {prof_last_name}: {result}")
        return result
    
    except Exception as e:
        print(f"Error retrieving RMP data for {prof_last_name}: {str(e)}")
        return result

def department_matches(rmp_dept, tamu_dept):
    """
    Check if the department on RateMyProfessors matches the TAMU department code
    
    Args:
        rmp_dept (str): Department name from RateMyProfessors
        tamu_dept (str): Department code from TAMU (e.g., "CSCE")
        
    Returns:
        bool: True if departments match, False otherwise
    """
    # Clean up the department strings
    rmp_dept = rmp_dept.strip().lower()
    tamu_dept = tamu_dept.strip().lower()
    
    # Direct match check first
    if tamu_dept in rmp_dept:
        return True
    
    # Dictionary mapping TAMU department codes to possible RMP department names
    dept_mappings = {
        # A
        "acct": ["accounting"],
        "aero": ["aerospace engineering", "aeronautical engineering"],
        "afst": ["africana studies", "african american studies"],
        "agec": ["agricultural economics"],
        "ansc": ["animal science"],
        "anth": ["anthropology"],
        "arch": ["architecture"],
        "arts": ["art", "studio art"],
        "astr": ["astronomy"],
        "atmo": ["atmospheric sciences", "meteorology"],
        
        # B
        "bich": ["biochemistry"],
        "bims": ["biomedical science"],
        "biol": ["biology"],
        "bmen": ["biomedical engineering"],
        "busn": ["business"],
        
        # C
        "chem": ["chemistry"],
        "chen": ["chemical engineering"],
        "clas": ["classics"],
        "comm": ["communication"],
        "cosc": ["construction science"],
        "csce": ["computer science", "computer engineering"],
        "cven": ["civil engineering"],
        
        # E
        "ecen": ["electrical engineering", "computer engineering", "electrical and computer engineering"],
        "econ": ["economics"],
        "engl": ["english"],
        "engr": ["engineering"],
        
        # F
        "finc": ["finance"],
        "fren": ["french"],
        
        # G
        "geog": ["geography"],
        "geol": ["geology"],
        "germ": ["german"],
        
        # H
        "hist": ["history"],
        "hlth": ["health"],
        
        # M
        "math": ["mathematics"],
        "meen": ["mechanical engineering"],
        "mgmt": ["management"],
        "mktg": ["marketing"],
        
        # P
        "perf": ["performance studies"],
        "pete": ["petroleum engineering"],
        "phil": ["philosophy"],
        "phys": ["physics"],
        "pols": ["political science"],
        
        # S
        "soci": ["sociology"],
        "span": ["spanish"],
        "stat": ["statistics"]
    }
    
    # Check if we have a mapping for this department
    if tamu_dept in dept_mappings:
        possible_names = dept_mappings[tamu_dept]
        for name in possible_names:
            if name in rmp_dept:
                return True
    
    # Special cases
    if tamu_dept == "csce" and ("computer" in rmp_dept or "computing" in rmp_dept):
        return True
    
    if tamu_dept == "ecen" and ("electrical" in rmp_dept or "electronic" in rmp_dept):
        return True
    
    return False

# Example usage
if __name__ == "__main__":
    # Test the function
    result = get_professor_rating("Jimenez", "CSCE")
    print(f"Overall Rating: {result['overall_rating']}")
    print(f"Would Take Again: {result['would_take_again']}")
    print(f"Difficulty: {result['difficulty']}")
    print(f"Comments: {result['comments']}")