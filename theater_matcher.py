"""
Theater Fuzzy Matcher
Finds matching theaters from user input with typo tolerance
"""

from difflib import get_close_matches
import json
from pathlib import Path
from typing import List, Dict, Optional


class TheaterMatcher:
    def __init__(self, theaters_file: str = "theaters.json"):
        """Initialize theater matcher with theater database"""
        self.theaters_file = Path(theaters_file)
        self.theaters = self._load_theaters()
        self._build_search_index()
    
    def _load_theaters(self) -> List[Dict]:
        """Load theaters from JSON file"""
        if not self.theaters_file.exists():
            print(f"Warning: {self.theaters_file} not found. No theaters loaded.")
            return []
        
        try:
            with open(self.theaters_file, 'r') as f:
                data = json.load(f)
                return data.get('theaters', [])
        except Exception as e:
            print(f"Error loading theaters: {e}")
            return []
    
    def _build_search_index(self):
        """Build searchable index of theater names and aliases"""
        self.search_index = {}
        
        for theater in self.theaters:
            slug = theater['slug']
            
            # Index by full name (lowercase)
            full_name = theater['name'].lower()
            self.search_index[full_name] = slug
            
            # Index by search terms
            for term in theater.get('search_terms', []):
                self.search_index[term.lower()] = slug
            
            # Index by slug
            self.search_index[slug] = slug
    
    def find_matches(self, user_input: str, max_results: int = 5) -> List[Dict]:
        """
        Find matching theaters using fuzzy search
        
        Returns list of matches sorted by relevance:
        [
            {
                'slug': 'amc-lincoln-square-13',
                'name': 'AMC Lincoln Square 13',
                'city': 'New York',
                'state': 'NY',
                'score': 0.95
            },
            ...
        ]
        """
        if not user_input or not self.search_index:
            return []
        
        user_input = user_input.lower().strip()
        
        # Strategy 1: Exact match
        if user_input in self.search_index:
            slug = self.search_index[user_input]
            theater = self._get_theater_by_slug(slug)
            if theater:
                theater['score'] = 1.0
                return [theater]
        
        # Strategy 2: Substring match (highest priority)
        substring_matches = []
        for search_term, slug in self.search_index.items():
            if user_input in search_term or search_term in user_input:
                theater = self._get_theater_by_slug(slug)
                if theater and theater not in substring_matches:
                    # Score based on how close the lengths are
                    score = min(len(user_input), len(search_term)) / max(len(user_input), len(search_term))
                    theater['score'] = score
                    substring_matches.append(theater)
        
        if substring_matches:
            # Sort by score (descending)
            substring_matches.sort(key=lambda x: x['score'], reverse=True)
            return substring_matches[:max_results]
        
        # Strategy 3: Fuzzy matching (typo tolerance)
        search_terms = list(self.search_index.keys())
        close_matches = get_close_matches(user_input, search_terms, n=max_results, cutoff=0.6)
        
        results = []
        for match in close_matches:
            slug = self.search_index[match]
            theater = self._get_theater_by_slug(slug)
            if theater and theater not in results:
                # Calculate similarity score
                score = self._similarity_score(user_input, match)
                theater['score'] = score
                results.append(theater)
        
        # Sort by score
        results.sort(key=lambda x: x['score'], reverse=True)
        return results[:max_results]
    
    def _get_theater_by_slug(self, slug: str) -> Optional[Dict]:
        """Get theater details by slug"""
        for theater in self.theaters:
            if theater['slug'] == slug:
                return theater.copy()
        return None
    
    def _similarity_score(self, str1: str, str2: str) -> float:
        """Calculate similarity score between two strings (0.0 to 1.0)"""
        from difflib import SequenceMatcher
        return SequenceMatcher(None, str1, str2).ratio()
    
    def get_theater_by_slug(self, slug: str) -> Optional[Dict]:
        """Public method to get theater by exact slug"""
        return self._get_theater_by_slug(slug)
    
    def list_all_theaters(self) -> List[Dict]:
        """Return all theaters in database"""
        return self.theaters.copy()


# Testing
if __name__ == "__main__":
    matcher = TheaterMatcher()
    
    print("Testing theater matcher...\n")
    
    test_queries = [
        "Lincoln Square",
        "lincoln sq",
        "Empire",
        "34th street",
        "kips bay",
        "Linkln Square",  # Typo
        "13",
        "imax"
    ]
    
    for query in test_queries:
        print(f"Query: '{query}'")
        matches = matcher.find_matches(query, max_results=3)
        
        if matches:
            for i, match in enumerate(matches, 1):
                print(f"  {i}. {match['name']} - Score: {match['score']:.2f}")
        else:
            print("  No matches found")
        print()
