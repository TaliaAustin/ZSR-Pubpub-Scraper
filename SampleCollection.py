"""
Single Collection PubPub Scraper
Scrapes one collection from PubPub and saves to Desktop
"""

import requests
from bs4 import BeautifulSoup
import json
import time
import random
import re
import os
from urllib.parse import urlparse, urljoin
from datetime import datetime
from pathlib import Path

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

class CollectionScraper:
    def __init__(self, collection_url, output_dir):
        self.collection_url = collection_url.rstrip('/')
        self.base_url = self.extract_base_url(collection_url)
        self.output_dir = Path(output_dir)
        
        # Statistics
        self.stats = {
            "start_time": datetime.now(),
            "publications_found": 0,
            "publications_processed": 0,
            "files_downloaded": 0,
            "download_failures": [],
            "errors": []
        }
        
        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def extract_base_url(self, url):
        """Extract base URL from collection URL"""
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"
    
    def get_collection_info(self):
        """Get collection title and metadata"""
        print("\n" + "="*70)
        print("📚 Analyzing Collection")
        print("="*70)
        print(f"URL: {self.collection_url}")
        
        try:
            response = requests.get(self.collection_url, headers=HEADERS, timeout=20)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extract collection title
            collection_title = "Unknown Collection"
            if soup.title:
                collection_title = soup.title.text.strip().split(' - ')[0].strip()
            
            print(f"Collection: {collection_title}")
            
            return {
                "title": collection_title,
                "url": self.collection_url,
                "soup": soup
            }
            
        except Exception as e:
            print(f"❌ Error accessing collection: {e}")
            return None
    
    def find_publications_in_collection(self, soup):
        """Find all publication URLs in the collection"""
        print("\n🔍 Finding publications in collection...")
        
        pub_urls = set()
        
        # Look for publication links
        for link in soup.find_all('a', href=True):
            href = link['href']
            
            # Check if it's a publication link
            if '/pub/' in href:
                # Convert to absolute URL
                if href.startswith('/'):
                    full_url = urljoin(self.base_url, href)
                elif href.startswith('http'):
                    full_url = href
                else:
                    continue
                
                # Remove query parameters but keep release info
                clean_url = full_url.split('?')[0]
                
                # Only include URLs from the same domain
                if clean_url.startswith(self.base_url):
                    pub_urls.add(clean_url)
        
        pub_list = sorted(list(pub_urls))
        self.stats["publications_found"] = len(pub_list)
        
        print(f"✅ Found {len(pub_list)} publications")
        
        if pub_list:
            print("\nSample publications:")
            for url in pub_list[:3]:
                print(f"  - {url}")
            if len(pub_list) > 3:
                print(f"  ... and {len(pub_list) - 3} more")
        
        return pub_list
    
    def extract_metadata(self, pub_url):
        """Extract metadata from publication page"""
        try:
            response = requests.get(pub_url, headers=HEADERS, timeout=20)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            metadata = {
                "url": pub_url,
                "title": "",
                "authors": [],
                "publication_date": "",
                "abstract": "",
                "doi": "",
                "license": "",
                "downloads": {},
                "extraction_date": datetime.now().isoformat()
            }
            
            # Extract title
            title_meta = soup.find("meta", attrs={"name": "citation_title"})
            if title_meta and title_meta.get("content"):
                metadata["title"] = title_meta["content"]
            elif soup.title:
                metadata["title"] = soup.title.text.strip().split(' - ')[0]
            
            # Extract authors
            author_metas = soup.find_all("meta", attrs={"name": "citation_author"})
            metadata["authors"] = [tag["content"] for tag in author_metas if tag.get("content")]
            
            # Extract publication date
            date_meta = soup.find("meta", attrs={"name": "citation_publication_date"})
            if date_meta and date_meta.get("content"):
                metadata["publication_date"] = date_meta["content"]
            
            # Extract abstract
            abstract_meta = soup.find("meta", attrs={"name": "citation_abstract"})
            if abstract_meta and abstract_meta.get("content"):
                metadata["abstract"] = abstract_meta["content"]
            
            # Extract DOI
            doi_meta = soup.find("meta", attrs={"name": "citation_doi"})
            if doi_meta and doi_meta.get("content"):
                metadata["doi"] = doi_meta["content"]
            
            # Extract license
            license_link = soup.find("a", href=re.compile(r"creativecommons.org"))
            if license_link:
                metadata["license"] = license_link.get("href", "")
            
            # Extract download links (PDF, DOCX, EPUB, JATS)
            for link in soup.find_all('a', href=True):
                href = link['href']
                link_text = link.get_text(strip=True).lower()
                
                # Look for assets.pubpub.org or s3.amazonaws.com/assets.pubpub.org
                is_asset = 'assets.pubpub.org' in href or 's3.amazonaws.com/assets.pubpub.org' in href
                
                if not is_asset:
                    continue
                
                # Identify format
                if '.pdf' in href.lower() or 'pdf' in link_text:
                    metadata["downloads"]["pdf"] = href if href.startswith('http') else urljoin(self.base_url, href)
                elif '.docx' in href.lower() or 'word' in link_text or 'docx' in link_text:
                    metadata["downloads"]["docx"] = href if href.startswith('http') else urljoin(self.base_url, href)
                elif '.epub' in href.lower() or 'epub' in link_text:
                    metadata["downloads"]["epub"] = href if href.startswith('http') else urljoin(self.base_url, href)
                elif '.xml' in href.lower() and ('jats' in link_text or 'xml' in link_text):
                    metadata["downloads"]["jats"] = href if href.startswith('http') else urljoin(self.base_url, href)
            
            return metadata
            
        except Exception as e:
            error_msg = f"Failed to extract metadata from {pub_url}: {e}"
            self.stats["errors"].append(error_msg)
            print(f"  ❌ {error_msg}")
            return None
    
    def download_file(self, url, save_path, max_retries=3):
        """Download file with retry mechanism"""
        for attempt in range(max_retries):
            try:
                response = requests.get(url, headers=HEADERS, stream=True, timeout=60)
                response.raise_for_status()
                
                # Ensure directory exists
                save_path.parent.mkdir(parents=True, exist_ok=True)
                
                with open(save_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                
                file_size = save_path.stat().st_size
                size_mb = file_size / (1024 * 1024)
                print(f"      ✅ {save_path.name} ({size_mb:.2f} MB)")
                
                self.stats["files_downloaded"] += 1
                return True
                
            except requests.exceptions.HTTPError as e:
                if attempt < max_retries - 1:
                    print(f"      ⚠️  HTTP {e.response.status_code}, retrying...")
                    time.sleep(2)
                else:
                    error_msg = f"HTTP {e.response.status_code}"
                    print(f"      ❌ Failed: {error_msg}")
                    self.stats["download_failures"].append({
                        "url": url,
                        "file": str(save_path),
                        "error": error_msg
                    })
                    return False
                    
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"      ⚠️  Error, retrying...")
                    time.sleep(5)
                else:
                    error_msg = str(e)
                    print(f"      ❌ Failed: {error_msg}")
                    self.stats["download_failures"].append({
                        "url": url,
                        "file": str(save_path),
                        "error": error_msg
                    })
                    return False
        
        return False
    
    def process_publication(self, pub_url, index, total):
        """Process a single publication"""
        print(f"\n[{index}/{total}] {pub_url}")
        
        # Extract metadata
        metadata = self.extract_metadata(pub_url)
        
        if not metadata:
            return None
        
        print(f"  📄 {metadata['title']}")
        if metadata['authors']:
            print(f"  👤 {', '.join(metadata['authors'])}")
        
        # Generate slug from URL
        path = urlparse(pub_url).path
        slug_match = re.search(r'/pub/([^/]+)', path)
        slug = slug_match.group(1) if slug_match else f"pub_{index}"
        
        # Create publication directory
        pub_dir = self.output_dir / slug
        pub_dir.mkdir(parents=True, exist_ok=True)
        
        # Download all available formats
        if metadata["downloads"]:
            print(f"  📥 Downloading files...")
            download_summary = {}
            
            for format_name, download_url in metadata["downloads"].items():
                # Determine filename
                if format_name == "jats":
                    filename = pub_dir / f"{slug}.xml"
                else:
                    filename = pub_dir / f"{slug}.{format_name}"
                
                # Download
                success = self.download_file(download_url, filename)
                download_summary[format_name] = {
                    "url": download_url,
                    "local_path": str(filename.relative_to(self.output_dir)),
                    "success": success
                }
            
            metadata["download_summary"] = download_summary
        else:
            print(f"  ⚠️  No download links found")
        
        # Save publication manifest
        manifest_path = pub_dir / "manifest.json"
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=4, ensure_ascii=False)
        
        self.stats["publications_processed"] += 1
        
        return metadata
    
    def save_collection_manifest(self, collection_info, all_publications):
        """Save collection manifest"""
        self.stats["end_time"] = datetime.now()
        
        collection_manifest = {
            "collection_name": collection_info["title"],
            "collection_url": self.collection_url,
            "extraction_start": self.stats["start_time"].isoformat(),
            "extraction_end": self.stats["end_time"].isoformat(),
            "duration": str(self.stats["end_time"] - self.stats["start_time"]),
            "statistics": {
                "publications_found": self.stats["publications_found"],
                "publications_processed": self.stats["publications_processed"],
                "files_downloaded": self.stats["files_downloaded"],
                "download_failures": len(self.stats["download_failures"]),
                "errors": len(self.stats["errors"])
            },
            "publications": all_publications,
            "download_failures": self.stats["download_failures"],
            "errors": self.stats["errors"]
        }
        
        manifest_path = self.output_dir / "collection-manifest.json"
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(collection_manifest, f, indent=4, ensure_ascii=False)
        
        return manifest_path
    
    def run(self):
        """Main execution"""
        print("\n" + "="*70)
        print("🚀 Collection Scraper")
        print("="*70)
        
        # Step 1: Get collection info
        collection_info = self.get_collection_info()
        
        if not collection_info:
            print("\n❌ Cannot access collection. Exiting.")
            return
        
        # Step 2: Find publications
        pub_urls = self.find_publications_in_collection(collection_info["soup"])
        
        if not pub_urls:
            print("\n❌ No publications found in collection. Exiting.")
            return
        
        # Confirmation
        print(f"\n📋 Ready to scrape:")
        print(f"   Collection: {collection_info['title']}")
        print(f"   Publications: {len(pub_urls)}")
        print(f"   Output: {self.output_dir}")
        
        confirm = input("\nProceed? (y/n): ").strip().lower()
        if confirm != 'y':
            print("Cancelled.")
            return
        
        # Step 3: Process each publication
        print("\n" + "="*70)
        print("📥 Downloading Publications")
        print("="*70)
        
        all_publications = []
        
        for i, pub_url in enumerate(pub_urls, 1):
            metadata = self.process_publication(pub_url, i, len(pub_urls))
            
            if metadata:
                all_publications.append(metadata)
            
            # Rate limiting (except for last item)
            if i < len(pub_urls):
                delay = random.uniform(1.5, 3.0)
                time.sleep(delay)
        
        # Step 4: Save collection manifest
        print("\n" + "="*70)
        print("💾 Saving Collection Manifest")
        print("="*70)
        
        manifest_path = self.save_collection_manifest(collection_info, all_publications)
        
        # Print summary
        print("\n" + "="*70)
        print("✅ SCRAPING COMPLETE")
        print("="*70)
        print(f"Collection: {collection_info['title']}")
        print(f"Publications found: {self.stats['publications_found']}")
        print(f"Publications processed: {self.stats['publications_processed']}")
        print(f"Files downloaded: {self.stats['files_downloaded']}")
        print(f"Download failures: {len(self.stats['download_failures'])}")
        print(f"Duration: {self.stats['end_time'] - self.stats['start_time']}")
        print(f"\n📁 Output directory: {self.output_dir.absolute()}")
        print(f"📄 Collection manifest: {manifest_path.name}")
        
        if self.stats["download_failures"]:
            print(f"\n⚠️  {len(self.stats['download_failures'])} download(s) failed. Check collection-manifest.json for details.")


def main():
    print("="*70)
    print("🚀 Single Collection PubPub Scraper")
    print("="*70)
    
    # Get collection URL
    print("\nStep 1: Get the collection URL")
    print("  (Go to the collection page in your browser and copy the URL)")
    print("  Example: https://urbanafrica.pubpub.org/collection/week-1")
    
    collection_url = input("\nEnter collection URL: ").strip()
    
    if not collection_url:
        print("❌ No URL provided. Exiting.")
        return
    
    if not collection_url.startswith('http'):
        collection_url = 'https://' + collection_url
    
    # Get output directory (default to Desktop)
    print("\nStep 2: Choose output location")
    desktop = Path.home() / "Desktop"
    default_output = desktop / "PubPub-Collection"
    
    print(f"  Default: {default_output}")
    custom_path = input("\nUse default location? (y/n): ").strip().lower()
    
    if custom_path == 'y' or custom_path == '':
        output_dir = default_output
    else:
        custom_location = input("Enter custom output directory: ").strip()
        output_dir = Path(custom_location)
    
    # Run scraper
    scraper = CollectionScraper(collection_url, output_dir)
    scraper.run()


if __name__ == "__main__":
    # Install: pip install requests beautifulsoup4 lxml
    main()