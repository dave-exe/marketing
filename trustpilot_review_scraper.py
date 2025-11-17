import requests
from bs4 import BeautifulSoup
import time
import random
from fake_useragent import UserAgent
import json
import pandas as pd
from datetime import datetime
import logging
import re
import os
from urllib.parse import urljoin, quote

class TrustpilotMultiScraper:
    def __init__(self):
        self.session = requests.Session()
        self.ua = UserAgent()
        self.setup_logging()
        
        # Headers realistici per Trustpilot
        self.base_headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'it-IT,it;q=0.8,en-US;q=0.5,en;q=0.3',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'DNT': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'same-origin',
        }
        
        # User agents realistici
        self.user_agents = [
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:120.0) Gecko/20100101 Firefox/120.0',
        ]
        
        # Statistiche globali
        self.global_stats = {
            'total_urls': 0,
            'successful_urls': 0,
            'failed_urls': 0,
            'total_reviews': 0,
            'start_time': None,
            'end_time': None
        }
    
    def setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('trustpilot_multi_scraper.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def get_random_headers(self):
        """Headers casuali per ogni richiesta"""
        headers = self.base_headers.copy()
        headers['User-Agent'] = random.choice(self.user_agents)
        return headers
    
    def safe_request(self, url, max_retries=3):
        """Richiesta sicura con gestione errori"""
        for attempt in range(max_retries):
            try:
                # Pausa casuale (Trustpilot è più permissivo)
                time.sleep(random.uniform(2, 4))
                
                headers = self.get_random_headers()
                response = self.session.get(url, headers=headers, timeout=15)
                
                # Controlla blocchi (Trustpilot raramente blocca)
                if response.status_code == 429:
                    self.logger.warning(f"Rate limit hit. Pausa di {30 * (attempt + 1)} secondi...")
                    time.sleep(30 * (attempt + 1))
                    continue
                
                response.raise_for_status()
                return response
                
            except requests.RequestException as e:
                self.logger.error(f"Errore richiesta (tentativo {attempt + 1}): {e}")
                if attempt == max_retries - 1:
                    return None
                time.sleep(5 * (attempt + 1))
        
        return None
    
    def extract_company_name_from_url(self, trustpilot_url):
        """Estrae il nome azienda dall'URL Trustpilot e gestisce parametri lingua intelligentemente"""
        if '/review/' in trustpilot_url:
            company_part = trustpilot_url.split('/review/')[-1]
            
            # Separa nome azienda da parametri
            if '?' in company_part:
                company_name = company_part.split('?')[0].strip('/')
                existing_params = company_part.split('?')[1]
                
                # Controlla se ha già parametri di lingua
                if 'languages=' in existing_params:
                    # Mantieni i parametri esistenti
                    self.url_params = '?' + existing_params
                    self.logger.info(f"Parametri lingua esistenti mantenuti: {existing_params}")
                else:
                    # Aggiungi languages=all ai parametri esistenti
                    self.url_params = '?' + existing_params + '&languages=all'
                    self.logger.info(f"Aggiunto languages=all ai parametri esistenti: {self.url_params}")
            else:
                # Nessun parametro esistente, aggiungi languages=all
                company_name = company_part.split('#')[0].strip('/')
                self.url_params = '?languages=all'
                self.logger.info(f"Nessun parametro esistente, aggiunto: {self.url_params}")
                
            return company_name
        return None
    
    def build_reviews_url(self, company_name, page=1):
        """Costruisce URL per le recensioni con paginazione"""
        base_url = f"https://www.trustpilot.com/review/{company_name}"
        
        # Aggiungi parametri esistenti se ci sono
        if hasattr(self, 'url_params') and self.url_params:
            base_url += self.url_params
            separator = '&'
        else:
            separator = '?'
        
        if page == 1:
            return base_url
        else:
            return f"{base_url}{separator}page={page}"
    
    def parse_review_element(self, review_element):
        """Estrae dati da una singola recensione"""
        try:
            review_data = {}
            
            # Rating (stelle) - Trustpilot usa data-service-review-rating
            rating_element = review_element.find('div', {'data-service-review-rating': True})
            if rating_element:
                rating = rating_element.get('data-service-review-rating')
                review_data['rating'] = int(rating) if rating else None
            else:
                # Alternativa: cerca nelle classi CSS
                star_element = review_element.find('div', class_=re.compile(r'star.*rating'))
                if star_element:
                    # Estrai rating dalle classi CSS
                    classes = star_element.get('class', [])
                    for cls in classes:
                        if 'star-' in str(cls):
                            match = re.search(r'star-(\d)', str(cls))
                            if match:
                                review_data['rating'] = int(match.group(1))
                                break
            
            # Titolo recensione
            title_selectors = [
                {'data-service-review-title-typography': 'true'},
                {'class': re.compile(r'.*title.*')},
                'h2'
            ]
            
            for selector in title_selectors:
                if isinstance(selector, str):
                    title_element = review_element.find(selector)
                else:
                    title_element = review_element.find('div', selector) or review_element.find('h2', selector)
                if title_element:
                    review_data['title'] = title_element.get_text(strip=True)
                    break
            
            # Testo recensione (rinominato come "review")
            text_selectors = [
                {'data-service-review-text-typography': 'true'},
                {'class': re.compile(r'.*review.*text.*')},
                'p'
            ]
            
            for selector in text_selectors:
                if isinstance(selector, str):
                    text_element = review_element.find(selector)
                else:
                    text_element = review_element.find('div', selector) or review_element.find('p', selector)
                if text_element:
                    review_data['review'] = text_element.get_text(strip=True)  # Rinominato da 'text' a 'review'
                    break
            
            # Data recensione
            date_element = review_element.find('time')
            if date_element:
                # Trustpilot usa attributo datetime
                datetime_attr = date_element.get('datetime')
                if datetime_attr:
                    review_data['date'] = datetime_attr
                else:
                    review_data['date'] = date_element.get_text(strip=True)
            
            # Nome recensore
            reviewer_selectors = [
                {'data-consumer-name-typography': 'true'},
                {'class': re.compile(r'.*consumer.*name.*')},
                {'class': re.compile(r'.*reviewer.*name.*')}
            ]
            
            for selector in reviewer_selectors:
                reviewer_element = review_element.find('div', selector) or review_element.find('span', selector)
                if reviewer_element:
                    review_data['reviewer'] = reviewer_element.get_text(strip=True)
                    break
            
            # Paese/Location
            location_element = review_element.find('div', {'data-consumer-country-typography': 'true'})
            if location_element:
                review_data['location'] = location_element.get_text(strip=True)
            
            # Verifica acquisto (se presente)
            verified_element = review_element.find('div', string=re.compile(r'Verified|verificato|acquisto', re.IGNORECASE))
            review_data['verified'] = verified_element is not None
            
            return review_data
            
        except Exception as e:
            self.logger.error(f"Errore parsing recensione: {e}")
            return None
    
    def scrape_reviews_page(self, company_name, page=1):
        """Scrapa una pagina di recensioni"""
        url = self.build_reviews_url(company_name, page)
        self.logger.info(f"Scraping pagina {page}: {url}")
        
        response = self.safe_request(url)
        if not response:
            self.logger.warning(f"Impossibile ottenere risposta per pagina {page}")
            return []
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Trustpilot: cerca container recensioni
        review_selectors = [
            {'class': re.compile(r'.*review.*card.*')},
            {'class': re.compile(r'.*review.*item.*')},
            {'data-service-review-card-paper': 'true'},
            'article'
        ]
        
        review_elements = []
        for selector in review_selectors:
            if isinstance(selector, str):
                elements = soup.find_all(selector)
            else:
                elements = soup.find_all('div', selector) or soup.find_all('article', selector)
            if elements:
                review_elements = elements
                self.logger.info(f"Trovati {len(elements)} elementi recensione con selettore: {selector}")
                break
        
        if not review_elements:
            # Fallback: cerca qualsiasi div che contenga rating
            review_elements = soup.find_all('div', {'data-service-review-rating': True})
            if review_elements:
                self.logger.info(f"Fallback: trovati {len(review_elements)} elementi con rating")
        
        reviews = []
        for element in review_elements:
            review_data = self.parse_review_element(element)
            if review_data and (review_data.get('review') or review_data.get('title')):  # Cambiato da 'text' a 'review'
                review_data['page'] = page
                review_data['scraped_at'] = datetime.now().isoformat()
                reviews.append(review_data)
        
        self.logger.info(f"Pagina {page}: {len(reviews)} recensioni estratte")
        return reviews
    
    def scrape_single_url(self, trustpilot_url, max_pages=50):
        """Scrapa un singolo URL con auto-stop"""
        try:
            company_name = self.extract_company_name_from_url(trustpilot_url)
            if not company_name:
                self.logger.error(f"Impossibile estrarre nome azienda dall'URL: {trustpilot_url}")
                return [], company_name
            
            self.logger.info(f"\n{'='*60}")
            self.logger.info(f"INIZIO SCRAPING: {company_name}")
            self.logger.info(f"URL: {trustpilot_url}")
            self.logger.info(f"{'='*60}")
            
            all_reviews = []
            consecutive_empty = 0
            
            for page in range(1, max_pages + 1):
                try:
                    self.logger.info(f"\n--- [{company_name}] Pagina {page} ---")
                    reviews = self.scrape_reviews_page(company_name, page)
                    
                    if not reviews or len(reviews) == 0:
                        consecutive_empty += 1
                        self.logger.warning(f"[{company_name}] Pagina {page} vuota - Consecutive empty: {consecutive_empty}/2")
                        
                        if consecutive_empty >= 2:
                            self.logger.info(f"[{company_name}] STOP: 2 pagine consecutive vuote")
                            break
                    else:
                        # Reset contatore se trova recensioni
                        if consecutive_empty > 0:
                            self.logger.info(f"[{company_name}] Recensioni trovate! Reset contatore (era {consecutive_empty})")
                        consecutive_empty = 0
                        
                        # Aggiungi brand name a ogni recensione
                        for review in reviews:
                            review['brand'] = company_name
                        
                        all_reviews.extend(reviews)
                        self.logger.info(f"[{company_name}] Pagina {page} OK - Totale: {len(all_reviews)} recensioni")
                    
                    # Pausa più lunga ogni 5 pagine
                    if page % 5 == 0 and page < max_pages:
                        pause = random.uniform(5, 10)
                        self.logger.info(f"[{company_name}] Pausa strategica: {pause:.1f}s")
                        time.sleep(pause)
                        
                except Exception as e:
                    consecutive_empty += 1
                    self.logger.error(f"[{company_name}] Errore pagina {page}: {e}")
                    self.logger.warning(f"[{company_name}] Errore contato come pagina vuota - Consecutive: {consecutive_empty}/2")
                    
                    if consecutive_empty >= 2:
                        self.logger.error(f"[{company_name}] STOP: 2 errori consecutivi")
                        break
                        
                    time.sleep(random.uniform(5, 10))
                    continue
            
            # Log finale per questo URL
            self.logger.info(f"\n[{company_name}] COMPLETATO:")
            self.logger.info(f"[{company_name}] Recensioni: {len(all_reviews)}")
            self.logger.info(f"[{company_name}] Ultima pagina: {page}")
            
            return all_reviews, company_name
            
        except Exception as e:
            self.logger.error(f"Errore critico per URL {trustpilot_url}: {e}")
            return [], None
    
    def save_single_csv(self, reviews, company_name, url_index):
        """Salva CSV per singolo URL con headers personalizzati"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Path Desktop
        desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
        
        # Nome file con company name pulito
        safe_company_name = re.sub(r'[^\w\-.]', '_', company_name) if company_name else f"url_{url_index}"
        filename = os.path.join(desktop_path, f"trustpilot_{safe_company_name}_{timestamp}.csv")
        
        if reviews:
            # Crea DataFrame con ordine colonne personalizzato
            df = pd.DataFrame(reviews)
            
            # Riordina colonne: review, title, rating, date, reviewer, verified, brand, page, scraped_at, location
            column_order = ['review', 'title', 'rating', 'date', 'reviewer', 'verified', 'brand', 'page', 'scraped_at']
            
            # Aggiungi location se esiste
            if 'location' in df.columns:
                column_order.append('location')
            
            # Riordina colonne (mantieni solo quelle che esistono)
            existing_columns = [col for col in column_order if col in df.columns]
            df = df[existing_columns]
            
            df.to_csv(filename, index=False, encoding='utf-8')
            
            # Statistiche
            stats = {
                'company_name': company_name,
                'total_reviews': len(reviews),
                'avg_rating': df['rating'].mean() if 'rating' in df.columns else None,
                'scraping_date': datetime.now().isoformat(),
                'unique_reviewers': df['reviewer'].nunique() if 'reviewer' in df.columns else None,
                'rating_distribution': df['rating'].value_counts().to_dict() if 'rating' in df.columns else {},
                'pages_scraped': sorted(df['page'].unique().tolist()) if 'page' in df.columns else []
            }
            
            self.logger.info(f"✅ [{company_name}] Salvato: {filename}")
            
        else:
            # File vuoto con headers corretti
            empty_columns = ['review', 'title', 'rating', 'date', 'reviewer', 'verified', 'brand', 'page', 'scraped_at', 'location']
            df = pd.DataFrame(columns=empty_columns)
            df.to_csv(filename, index=False, encoding='utf-8')
            
            stats = {
                'company_name': company_name,
                'total_reviews': 0,
                'avg_rating': None,
                'scraping_date': datetime.now().isoformat(),
                'unique_reviewers': 0,
                'rating_distribution': {},
                'note': 'Nessuna recensione trovata'
            }
            
            self.logger.info(f"📝 [{company_name}] File vuoto creato: {filename}")
        
        # Salva statistiche
        stats_filename = os.path.join(desktop_path, f"trustpilot_{safe_company_name}_{timestamp}_stats.json")
        with open(stats_filename, 'w') as f:
            json.dump(stats, f, indent=2)
        
        return filename, len(reviews)
    
    def scrape_multiple_urls(self, trustpilot_urls, max_pages_per_url=50):
        """Scrapa multiple URLs sequenzialmente"""
        self.global_stats['start_time'] = datetime.now().isoformat()
        self.global_stats['total_urls'] = len(trustpilot_urls)
        
        self.logger.info(f"\n🚀 INIZIO SCRAPING MULTI-URL")
        self.logger.info(f"📊 URLs da processare: {len(trustpilot_urls)}")
        self.logger.info(f"📄 Max pagine per URL: {max_pages_per_url}")
        
        results = []
        
        for index, url in enumerate(trustpilot_urls, 1):
            try:
                self.logger.info(f"\n🎯 PROCESSANDO URL {index}/{len(trustpilot_urls)}")
                
                # Scrapa singolo URL
                reviews, company_name = self.scrape_single_url(url, max_pages_per_url)
                
                if reviews:
                    # Salva CSV
                    filename, review_count = self.save_single_csv(reviews, company_name, index)
                    
                    results.append({
                        'url': url,
                        'company': company_name,
                        'reviews_count': review_count,
                        'status': 'success',
                        'filename': filename
                    })
                    
                    self.global_stats['successful_urls'] += 1
                    self.global_stats['total_reviews'] += review_count
                    
                    self.logger.info(f"✅ [{company_name}] SUCCESSO: {review_count} recensioni")
                    
                else:
                    # URL fallito o senza recensioni
                    filename, _ = self.save_single_csv([], company_name or f"url_{index}", index)
                    
                    results.append({
                        'url': url,
                        'company': company_name or 'unknown',
                        'reviews_count': 0,
                        'status': 'no_reviews',
                        'filename': filename
                    })
                    
                    self.global_stats['failed_urls'] += 1
                    self.logger.warning(f"❌ [{company_name or 'unknown'}] NESSUNA RECENSIONE")
                
                # Pausa tra URLs per essere rispettosi
                if index < len(trustpilot_urls):
                    inter_url_pause = random.uniform(10, 20)
                    self.logger.info(f"⏱️  Pausa inter-URL: {inter_url_pause:.1f}s")
                    time.sleep(inter_url_pause)
                    
            except Exception as e:
                self.logger.error(f"❌ ERRORE CRITICO URL {index}: {e}")
                
                results.append({
                    'url': url,
                    'company': 'error',
                    'reviews_count': 0,
                    'status': 'error',
                    'filename': None,
                    'error': str(e)
                })
                
                self.global_stats['failed_urls'] += 1
                continue
        
        # Report finale
        self.global_stats['end_time'] = datetime.now().isoformat()
        self.generate_final_report(results)
        
        return results
    
    def generate_final_report(self, results):
        """Genera report finale"""
        self.logger.info(f"\n{'='*80}")
        self.logger.info(f"🏁 SCRAPING MULTI-URL COMPLETATO")
        self.logger.info(f"{'='*80}")
        
        self.logger.info(f"📊 STATISTICHE GLOBALI:")
        self.logger.info(f"   • URLs totali: {self.global_stats['total_urls']}")
        self.logger.info(f"   • URLs riusciti: {self.global_stats['successful_urls']}")
        self.logger.info(f"   • URLs falliti: {self.global_stats['failed_urls']}")
        self.logger.info(f"   • Recensioni totali: {self.global_stats['total_reviews']}")
        
        self.logger.info(f"\n📋 DETTAGLIO PER URL:")
        for result in results:
            status_icon = "✅" if result['status'] == 'success' else "❌" if result['status'] == 'error' else "⚠️"
            self.logger.info(f"   {status_icon} {result['company']}: {result['reviews_count']} recensioni")
        
        # Salva report JSON
        desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_filename = os.path.join(desktop_path, f"trustpilot_multi_report_{timestamp}.json")
        
        report_data = {
            'global_stats': self.global_stats,
            'results': results,
            'generated_at': datetime.now().isoformat()
        }
        
        with open(report_filename, 'w') as f:
            json.dump(report_data, f, indent=2)
        
        self.logger.info(f"\n📄 Report dettagliato salvato: {report_filename}")

# ESEMPIO DI UTILIZZO MULTI-URL
if __name__ == "__main__":
    scraper = TrustpilotMultiScraper()
    
    # Lista di URLs da processare
    trustpilot_urls = [
        "URL1",
        # Aggiungi altri URL qui
    ]
    
    try:
        print("🚀 Avvio scraping multi-URL Trustpilot")
        print(f"📊 URLs da processare: {len(trustpilot_urls)}")
        print("⏹️  Ogni URL si ferma dopo 2 pagine consecutive vuote")
        print("💾 Un CSV separato per ogni URL sul Desktop")
        
        # Scraping multi-URL
        results = scraper.scrape_multiple_urls(trustpilot_urls, max_pages_per_url=20)
        
        # Riepilogo finale
        successful = sum(1 for r in results if r['status'] == 'success')
        total_reviews = sum(r['reviews_count'] for r in results)
        
        print(f"\n🎉 PROCESSO COMPLETATO!")
        print(f"✅ URLs riusciti: {successful}/{len(trustpilot_urls)}")
        print(f"📊 Recensioni totali: {total_reviews}")
        print(f"💾 File CSV creati sul Desktop")
        
        # Mostra dettagli
        print(f"\n📋 RIEPILOGO:")
        for result in results:
            status_emoji = "✅" if result['status'] == 'success' else "❌"
            print(f"   {status_emoji} {result['company']}: {result['reviews_count']} recensioni")
        
    except KeyboardInterrupt:
        print("\n⏹️ Processo interrotto dall'utente")
    except Exception as e:
        print(f"❌ Errore critico: {e}")
