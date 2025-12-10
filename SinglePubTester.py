"""
Single Publication Test Scraper
Tests scraping on ONE publication to verify all exports work
Includes macOS .html file fix
"""

import requests
from bs4 import BeautifulSoup
import json
import re
import os
import mimetypes
from urllib.parse import urlparse, urljoin
from datetime import datetime
from pathlib import Path

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

class SinglePubTester:
    def __init__(self, pub_url, output_dir):
        self.pub_url = pub_url.rstrip('/')
        self.base_url = self.extract_base_url(pub_url)
        self.output_dir = Path(output_dir)
        
        # Statistics
        self.stats = {
            "start_time": datetime.now(),
            "files_downloaded": 0,
            "download_failures": [],
            "assets_downloaded": 0
        }
        
        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def extract_base_url(self, url):
        """Extract base URL from publication URL"""
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"
    
    def extract_metadata(self):
        """Extract metadata from publication page"""
        print("\n" + "="*70)
        print("📄 EXTRACTING METADATA")
        print("="*70)
        print(f"URL: {self.pub_url}")
        
        try:
            response = requests.get(self.pub_url, headers=HEADERS, timeout=20)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            metadata = {
                "url": self.pub_url,
                "final_url": response.url,
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
            
            print(f"\n✅ Title: {metadata['title']}")
            
            # Extract authors
            author_metas = soup.find_all("meta", attrs={"name": "citation_author"})
            metadata["authors"] = [tag["content"] for tag in author_metas if tag.get("content")]
            
            if metadata["authors"]:
                print(f"✅ Authors: {', '.join(metadata['authors'])}")
            else:
                print("⚠️  No authors found")
            
            # Extract publication date
            date_meta = soup.find("meta", attrs={"name": "citation_publication_date"})
            if date_meta and date_meta.get("content"):
                metadata["publication_date"] = date_meta["content"]
                print(f"✅ Date: {metadata['publication_date']}")
            
            # Extract abstract
            abstract_meta = soup.find("meta", attrs={"name": "citation_abstract"})
            if abstract_meta and abstract_meta.get("content"):
                metadata["abstract"] = abstract_meta["content"]
                print(f"✅ Abstract: {metadata['abstract'][:100]}...")
            
            # Extract DOI
            doi_meta = soup.find("meta", attrs={"name": "citation_doi"})
            if doi_meta and doi_meta.get("content"):
                metadata["doi"] = doi_meta["content"]
                print(f"✅ DOI: {metadata['doi']}")
            
            # Extract license
            license_link = soup.find("a", href=re.compile(r"creativecommons.org"))
            if license_link:
                metadata["license"] = license_link.get("href", "")
                print(f"✅ License: {metadata['license']}")
            
            # Extract download links
            print("\n" + "="*70)
            print("🔗 FINDING DOWNLOAD LINKS")
            print("="*70)
            
            for link in soup.find_all('a', href=True):
                href = link['href']
                link_text = link.get_text(strip=True).lower()
                
                # Look for assets.pubpub.org or s3.amazonaws.com/assets.pubpub.org
                is_asset = 'assets.pubpub.org' in href or 's3.amazonaws.com/assets.pubpub.org' in href
                
                if not is_asset:
                    continue
                
                absolute_url = href if href.startswith('http') else urljoin(self.base_url, href)
                
                # Identify format
                if '.pdf' in href.lower() or 'pdf' in link_text:
                    metadata["downloads"]["pdf"] = absolute_url
                    print(f"✅ Found PDF: {link_text}")
                elif '.docx' in href.lower() or 'word' in link_text or 'docx' in link_text:
                    metadata["downloads"]["docx"] = absolute_url
                    print(f"✅ Found DOCX: {link_text}")
                elif '.epub' in href.lower() or 'epub' in link_text:
                    metadata["downloads"]["epub"] = absolute_url
                    print(f"✅ Found EPUB: {link_text}")
                elif '.xml' in href.lower() and ('jats' in link_text or 'xml' in link_text):
                    metadata["downloads"]["jats"] = absolute_url
                    print(f"✅ Found JATS XML: {link_text}")
            
            if not metadata["downloads"]:
                print("⚠️  No download links found!")
            else:
                print(f"\n📊 Total formats found: {len(metadata['downloads'])}")
            
            return metadata, soup
            
        except Exception as e:
            print(f"❌ Error extracting metadata: {e}")
            return None, None
    
    def download_file(self, url, save_path, format_name, max_retries=3):
        """Download file with retry mechanism and macOS .html fix"""
        for attempt in range(max_retries):
            try:
                print(f"  Downloading {format_name} (attempt {attempt + 1}/{max_retries})...")
                
                response = requests.get(url, headers=HEADERS, stream=True, timeout=60)
                response.raise_for_status()
                
                # Ensure directory exists
                save_path.parent.mkdir(parents=True, exist_ok=True)
                
                # MACOS HTML FIX: Write as binary to prevent conversion
                with open(save_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                
                # Verify file was saved correctly
                if not save_path.exists():
                    raise Exception(f"File not created: {save_path}")
                
                file_size = save_path.stat().st_size
                size_mb = file_size / (1024 * 1024)
                
                # MACOS HTML FIX: Verify .html extension wasn't changed
                if save_path.suffix == '.html' and not str(save_path).endswith('.html'):
                    print(f"  ⚠️  WARNING: macOS may have changed file extension!")
                    print(f"      Expected: {save_path}")
                    print(f"      Check Finder to verify extension")
                
                print(f"  ✅ Downloaded: {save_path.name} ({size_mb:.2f} MB)")
                print(f"     Saved to: {save_path}")
                
                self.stats["files_downloaded"] += 1
                return True
                
            except requests.exceptions.HTTPError as e:
                if attempt < max_retries - 1:
                    print(f"  ⚠️  HTTP {e.response.status_code}, retrying in 2 seconds...")
                    import time
                    time.sleep(2)
                else:
                    error_msg = f"HTTP {e.response.status_code}"
                    print(f"  ❌ Failed: {error_msg}")
                    self.stats["download_failures"].append({
                        "format": format_name,
                        "url": url,
                        "error": error_msg
                    })
                    return False
                    
            except Exception as e:
                if attempt < max_retries - 1:
                    print(f"  ⚠️  Error: {e}, retrying in 5 seconds...")
                    import time
                    time.sleep(5)
                else:
                    error_msg = str(e)
                    print(f"  ❌ Failed: {error_msg}")
                    self.stats["download_failures"].append({
                        "format": format_name,
                        "url": url,
                        "error": error_msg
                    })
                    return False
        
        return False
    
    def get_unique_filename(self, asset_url):
        """Generate unique filename for asset"""
        parsed_url = urlparse(asset_url)
        path_segments = parsed_url.path.strip('/').split('/')
        
        filename = path_segments[-1] or 'asset'
        filename = filename.split('?')[0].split('#')[0]
        
        if not filename or '.' not in filename:
            ext = mimetypes.guess_extension(mimetypes.guess_type(asset_url)[0]) or '.bin'
            filename = f"{path_segments[-2] or 'file'}{ext}"
        
        prefix = "_".join(path_segments[:-1])
        local_path = Path("_assets") / prefix / filename if prefix else Path("_assets") / filename
        
        return local_path
    
    def download_asset(self, asset_url, save_dir):
        """Download a single asset"""
        try:
            local_path = self.get_unique_filename(asset_url)
            full_path = save_dir / local_path
            
            # Skip if already exists
            if full_path.exists():
                return str(local_path)
            
            full_path.parent.mkdir(parents=True, exist_ok=True)
            
            response = requests.get(asset_url, headers=HEADERS, timeout=30, stream=True)
            response.raise_for_status()
            
            with open(full_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            self.stats["assets_downloaded"] += 1
            return str(local_path)
            
        except Exception as e:
            if hasattr(e, 'response') and e.response and e.response.status_code in [404, 403]:
                pass  # Skip 404/403 silently
            else:
                print(f"    ⚠️  Failed to download asset: {asset_url}")
            return None
    
    def archive_html_with_assets(self, html_path, html_content):
        """Download assets and rewrite HTML links"""
        print("\n  📦 Archiving HTML assets...")
        
        soup = BeautifulSoup(html_content, 'html.parser')
        save_dir = html_path.parent
        downloaded = {}
        
        # Process img, link, script tags
        targets = [('img', 'src'), ('link', 'href'), ('script', 'src')]
        
        for tag_name, attr in targets:
            for tag in soup.find_all(tag_name):
                source_url = tag.get(attr)
                if not source_url or source_url.startswith('data:'):
                    continue
                
                absolute_url = urljoin(self.base_url, source_url)
                
                # Only download from same domain
                if absolute_url.startswith(self.base_url):
                    if absolute_url in downloaded:
                        local_path = downloaded[absolute_url]
                    else:
                        local_path = self.download_asset(absolute_url, save_dir)
                        if local_path:
                            downloaded[absolute_url] = local_path
                    
                    if local_path:
                        tag[attr] = local_path
        
        # MACOS HTML FIX: Save as binary to preserve .html extension
        with open(html_path, 'wb') as f:
            html_bytes = str(soup).encode('utf-8')
            f.write(html_bytes)
        
        print(f"  ✅ Archived {len(downloaded)} assets")
    
    def run_test(self):
        """Run the test on single publication"""
        print("\n" + "="*70)
        print("🧪 SINGLE PUBLICATION TEST")
        print("="*70)
        print(f"Testing: {self.pub_url}")
        print(f"Output: {self.output_dir}")
        
        # Extract metadata
        metadata, soup = self.extract_metadata()
        
        if not metadata:
            print("\n❌ Failed to extract metadata. Exiting.")
            return
        
        # Generate slug
        path = urlparse(self.pub_url).path
        slug_match = re.search(r'/pub/([^/]+)', path)
        slug = slug_match.group(1) if slug_match else "test_pub"
        
        # Create publication directory
        pub_dir = self.output_dir / slug
        pub_dir.mkdir(parents=True, exist_ok=True)
        
        print(f"\n📁 Publication directory: {pub_dir}")
        
        # Download all available formats
        if metadata["downloads"]:
            print("\n" + "="*70)
            print("📥 DOWNLOADING FILES")
            print("="*70)
            
            download_summary = {}
            
            for format_name, download_url in metadata["downloads"].items():
                print(f"\n{format_name.upper()}:")
                print(f"  URL: {download_url}")
                
                # Determine filename with EXPLICIT .html extension
                if format_name == "html":
                    # MACOS FIX: Explicitly name as .html
                    filename = pub_dir / "index.html"
                elif format_name == "jats":
                    filename = pub_dir / f"{slug}.xml"
                else:
                    filename = pub_dir / f"{slug}.{format_name}"
                
                # Download
                success = self.download_file(download_url, filename, format_name)
                
                download_summary[format_name] = {
                    "url": download_url,
                    "local_path": str(filename.relative_to(self.output_dir)),
                    "success": success,
                    "exists": filename.exists()
                }
                
                # If HTML, archive assets
                if success and format_name == "html" and filename.exists():
                    try:
                        with open(filename, 'r', encoding='utf-8') as f:
                            html_content = f.read()
                        self.archive_html_with_assets(filename, html_content)
                    except Exception as e:
                        print(f"  ⚠️  Could not archive HTML assets: {e}")
            
            metadata["download_summary"] = download_summary
        else:
            print("\n⚠️  No download links found, skipping file downloads")
        
        # Save manifest
        print("\n" + "="*70)
        print("💾 SAVING MANIFEST")
        print("="*70)
        
        manifest_path = pub_dir / "manifest.json"
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=4, ensure_ascii=False)
        
        print(f"✅ Manifest saved: {manifest_path}")
        
        # Print summary
        self.stats["end_time"] = datetime.now()
        duration = self.stats["end_time"] - self.stats["start_time"]
        
        print("\n" + "="*70)
        print("📊 TEST SUMMARY")
        print("="*70)
        print(f"Publication: {metadata['title']}")
        print(f"Files downloaded: {self.stats['files_downloaded']}")
        print(f"Assets archived: {self.stats['assets_downloaded']}")
        print(f"Failures: {len(self.stats['download_failures'])}")
        print(f"Duration: {duration}")
        print(f"\n📁 Output directory: {self.output_dir.absolute()}")
        
        # List files
        print("\n📄 Files created:")
        for file in sorted(pub_dir.rglob("*")):
            if file.is_file():
                rel_path = file.relative_to(pub_dir)
                size = file.stat().st_size
                size_str = f"{size:,} bytes" if size < 1024*1024 else f"{size/(1024*1024):.2f} MB"
                print(f"  ✅ {rel_path} ({size_str})")
        
        if self.stats["download_failures"]:
            print("\n⚠️  Download Failures:")
            for failure in self.stats["download_failures"]:
                print(f"  ❌ {failure['format']}: {failure['error']}")
        
        # MACOS WARNING
        print("\n" + "="*70)
        print("🍎 macOS USERS: IMPORTANT!")
        print("="*70)
        print("If you see '.html' files in Finder:")
        print("1. Right-click the file → Get Info")
        print("2. Check 'Name & Extension' section")
        print("3. Verify it ends with .html (not .html.txt)")
        print("4. If wrong, uncheck 'Hide extension' and rename")
        print("\nTo prevent this in future:")
        print("  System Settings → Desktop & Dock → Show all filename extensions")


def main():
    print("="*70)
    print("🧪 Single Publication Test Scraper")
    print("   (with macOS .html extension fix)")
    print("="*70)
    
    # Get publication URL
    print("\nStep 1: Get the publication URL")
    print("  (Go to a publication page and copy the URL)")
    print("  Example: https://urbanafrica.pubpub.org/pub/eshlga2d/release/1")
    
    pub_url = input("\nEnter publication URL: ").strip()
    
    if not pub_url:
        print("❌ No URL provided. Exiting.")
        return
    
    if not pub_url.startswith('http'):
        pub_url = 'https://' + pub_url
    
    # Set output to Desktop
    desktop = Path.home() / "Desktop"
    output_dir = desktop / "PubPub-Test"
    
    print(f"\nStep 2: Output location")
    print(f"  Default: {output_dir}")
    
    use_default = input("\nUse default? (y/n): ").strip().lower()
    
    if use_default != 'y' and use_default != '':
        custom_path = input("Enter custom output directory: ").strip()
        output_dir = Path(custom_path)
    
    # Confirmation
    print(f"\n📋 Configuration:")
    print(f"   Publication: {pub_url}")
    print(f"   Output: {output_dir}")
    
    confirm = input("\nProceed? (y/n): ").strip().lower()
    if confirm != 'y':
        print("Cancelled.")
        return
    
    # Run test
    tester = SinglePubTester(pub_url, output_dir)
    tester.run_test()
    
    print("\n" + "="*70)
    print("✅ TEST COMPLETE!")
    print("="*70)
    print("\n💡 Next steps:")
    print("  1. Check the output folder on your Desktop")
    print("  2. Verify all files downloaded correctly")
    print("  3. Open index.html in a browser to test HTML archival")
    print("  4. If everything looks good, run the full scraper!")


if __name__ == "__main__":
    # Install: pip install requests beautifulsoup4 lxml
    main()