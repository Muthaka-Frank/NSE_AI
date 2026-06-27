"""
NSE AI Platform — News Relevance Engine
Computes semantic relevance score of ticker matches in news articles to filter noise.
"""

import re

# High-relevance business/financial keywords
FINANCIAL_KEYWORDS = {
    "profit", "profits", "loss", "losses", "revenue", "revenues", "sales", 
    "earnings", "dividend", "dividends", "share", "shares", "stock", "stocks", 
    "acquisition", "acquisitions", "merger", "mergers", "buyout", "regulatory", 
    "tax", "taxes", "vat", "tariff", "tariffs", "growth", "shrink", "decline", 
    "debt", "bond", "bonds", "court", "fined", "fine", "lawsuit", "sued", "invests", 
    "investment", "investments", "capital", "funding", "ceo", "board", "margin", 
    "margins", "hike", "cut", "quarter", "fiscal", "year", "results", "statement", 
    "audited", "unaudited", "performance", "outlook", "guidance"
}

# Low-relevance PR/CSR/noise keywords
PR_KEYWORDS = {
    "sponsor", "sponsors", "sponsorship", "sponsored", "donation", "donated", 
    "donating", "donations", "orphanage", "charity", "csr", "csr-activity", 
    "marathon", "athletics", "football", "soccer", "tournament", "golf", "cup", 
    "award", "awards", "ceremony", "awarded", "winning", "winner", "celebrates", 
    "celebrated", "pride", "graduates", "graduation", "scholarship", "scholarships", 
    "wishes", "congratulates", "congratulations"
}

def split_into_sentences(text: str) -> list[str]:
    # Split text by sentence boundaries (. ! ?)
    sentences = re.split(r'(?<=[.!?])\s+', text)
    return [s.strip() for s in sentences if s.strip()]

def evaluate_relevance(ticker: str, company_name: str, title: str, summary: str, total_matches: int = 1) -> float:
    """
    Evaluate the semantic relevance of a stock ticker match to a news article.
    Returns a score between 0.0 and 1.0.
    """
    score = 0.0
    title_lower = title.lower()
    summary_lower = summary.lower()
    ticker_lower = ticker.lower()
    
    # We clean suffixes from company name for matching
    cleaned_name = company_name
    for suffix in ["PLC", "Limited", "Ltd", "Group", "Holdings", "Holding", "Co.", "Co", "Ltd.", "Company"]:
        cleaned_name = re.sub(rf"\b{suffix}\b", "", cleaned_name, flags=re.IGNORECASE)
    name_lower = cleaned_name.strip().lower()
    
    # 1. Mention Location Base Score
    # Check if either ticker or cleaned name is in title/summary
    in_title = (ticker_lower in title_lower) or (name_lower in title_lower)
    in_summary = (ticker_lower in summary_lower) or (name_lower in summary_lower)
    
    if in_title:
        score += 0.60
    elif in_summary:
        score += 0.30
    else:
        # Not mentioned in title or summary (should not happen, but return 0 just in case)
        return 0.0

    # 2. Sentence-level Keyword Context Check
    # Find all sentences that contain the company name or ticker
    all_text = title + " " + summary
    sentences = split_into_sentences(all_text)
    relevant_sentences = []
    
    for s in sentences:
        s_lower = s.lower()
        if (ticker_lower in s_lower) or (name_lower in s_lower):
            relevant_sentences.append(s_lower)
            
    # Check for proximity to business/financial keywords inside those matching sentences
    has_financial_context = False
    has_pr_context = False
    
    for s in relevant_sentences:
        words = re.findall(r"\b\w+\b", s)
        for w in words:
            if w in FINANCIAL_KEYWORDS:
                has_financial_context = True
            if w in PR_KEYWORDS:
                has_pr_context = True
                
    if has_financial_context:
        score += 0.30
    else:
        # If no direct financial keyword is in the matching sentence, check if it's anywhere in the article
        article_words = re.findall(r"\b\w+\b", all_text.lower())
        if any(w in FINANCIAL_KEYWORDS for w in article_words):
            score += 0.15

    # 3. PR/CSR penalty
    if has_pr_context:
        score -= 0.25

    # 4. Multi-company density penalty (Generic market roundup filter)
    # If the article tags too many companies, each individual company is less likely to be the core focus
    if total_matches >= 4:
        score *= 0.50
    elif total_matches == 3:
        score *= 0.80

    # Clamp score to [0.0, 1.0]
    return max(0.0, min(1.0, round(score, 3)))
