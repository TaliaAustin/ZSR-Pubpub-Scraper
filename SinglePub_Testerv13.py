"""
Single Publication Test Scraper - FINAL CLEAN VERSION
Tests scraping on ONE publication to verify all exports work
Includes:
- macOS .html file fix
- Stable image filenames (slug + URL hash)
- assets/images/ directory structure
- Relative path rewriting for offline viewing

Installation: pip install requests beautifulsoup4 lxml
"""

import requests
from bs4 import BeautifulSoup
import json
import re
import os
import mimetypes
import hashlib
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
            
            # Format mapping for detection
            format_patterns = {
                'pdf': ['pdf', '.pdf'],
                'docx': ['word', 'docx', '.docx'],
                'markdown': ['markdown', '.md'],
                'epub': ['epub', '.epub'],
                'html': ['html', '.html', '.htm'],
                'odt': ['opendocument', 'odt', '.odt'],
                'txt': ['plain text', 'text', '.txt'],
                'jats': ['jats', 'xml', '.xml'],
                'latex': ['latex', 'tex', '.tex']
            }
            
            for link in soup.find_all('a', href=True):
                href = link['href']
                link_text = link.get_text(strip=True).lower()
                
                # Look for PubPub asset links
                is_asset = 'assets.pubpub.org' in href or 's3.amazonaws.com/assets.pubpub.org' in href
                
                if not is_asset:
                    continue
                
                absolute_url = href if href.startswith('http') else urljoin(self.base_url, href)
                
                # Check against all format patterns
                for format_name, patterns in format_patterns.items():
                    if any(pattern in href.lower() or pattern in link_text for pattern in patterns):
                        # Special handling for JATS XML (avoid non-JATS XML files)
                        if format_name == 'jats':
                            if not ('jats' in link_text or 'xml' in link_text):
                                continue
                        
                        # Don't overwrite if already found
                        if format_name not in metadata["downloads"]:
                            metadata["downloads"][format_name] = absolute_url
                            print(f"✅ Found {format_name.upper()}: {link_text}")
                        break
            
            if not metadata["downloads"]:
                print("⚠️  No download links found!")
            else:
                print(f"\n📊 Total formats found: {len(metadata['downloads'])}")
                print(f"   Formats: {', '.join(metadata['downloads'].keys())}")
            
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
    
    def archive_html_with_assets(self, html_path, html_content, pub_slug):
        """Download assets and rewrite HTML links to relative paths with stable filenames"""
        print("\n  📦 Archiving HTML assets...")
        print(f"  📄 HTML file size: {len(html_content)} bytes")
        
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # DEBUG: Check what images are in the HTML
        all_images = soup.find_all('img')
        print(f"  🔍 Found {len(all_images)} <img> tags in HTML")
        
        if len(all_images) > 0:
            print(f"  📸 Sample image sources:")
            for img in all_images[:3]:
                src = img.get('src', 'NO SRC ATTRIBUTE')
                srcset = img.get('srcset', '')
                if src and src != 'NO SRC ATTRIBUTE':
                    print(f"     - src: {src[:80]}")
                if srcset:
                    print(f"     - srcset: {srcset[:80]}")
        
        # Create assets/images directory next to the HTML file
        assets_dir = html_path.parent / "assets"
        images_dir = assets_dir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        print(f"  📁 Created directory: {images_dir}")
        
        downloaded_images = {}
        failed_downloads = 0
        
        # Process all image tags
        for img_tag in soup.find_all('img'):
            # Get src attribute
            src = img_tag.get('src')
            srcset = img_tag.get('srcset')
            
            # PubPub often uses srcSet instead of src
            image_url = None
            if srcset:
                # Parse srcset to get first URL
                srcset_parts = srcset.split(',')[0].strip().split(' ')[0]
                image_url = srcset_parts
                print(f"    📸 Found image in srcset: {image_url[:60]}...")
            elif src:
                image_url = src
                print(f"    📸 Found image in src: {image_url[:60]}...")
            else:
                print(f"    ⚠️  Image tag with no src or srcset attribute")
                continue
                
            if image_url.startswith('data:'):
                print(f"    ⏭️  Skipping data URI image")
                continue
            
            # Convert to absolute URL
            if image_url.startswith('http'):
                absolute_url = image_url
            else:
                absolute_url = urljoin(self.base_url, image_url)
            
            print(f"    📥 Downloading: {absolute_url[:80]}...")
            
            # Check if already downloaded
            if absolute_url in downloaded_images:
                local_path = downloaded_images[absolute_url]
                img_tag['src'] = local_path
                # Remove srcset to use our local src
                if img_tag.get('srcset'):
                    del img_tag['srcset']
                print(f"       ✅ Already downloaded as: {local_path}")
                continue
            
            try:
                # Download the image
                response = requests.get(absolute_url, headers=HEADERS, timeout=30, stream=True)
                response.raise_for_status()
                
                # Read content for hashing
                content = b''
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        content += chunk
                
                # Generate stable filename: slug + hash of URL
                url_hash = hashlib.md5(absolute_url.encode()).hexdigest()[:8]
                
                # Get file extension from URL or content-type
                parsed_url = urlparse(absolute_url)
                original_filename = Path(parsed_url.path).name.split('?')[0]
                
                if '.' in original_filename:
                    ext = Path(original_filename).suffix
                else:
                    # Guess from content-type
                    content_type = response.headers.get('content-type', '')
                    ext = mimetypes.guess_extension(content_type) or '.jpg'
                
                # Stable filename: slug_hash.ext
                stable_filename = f"{pub_slug}_{url_hash}{ext}"
                image_path = images_dir / stable_filename
                
                # Write image file
                with open(image_path, 'wb') as f:
                    f.write(content)
                
                # Verify file was created
                if not image_path.exists():
                    print(f"       ❌ File not created: {image_path}")
                    failed_downloads += 1
                    continue
                
                file_size = image_path.stat().st_size
                print(f"       ✅ Saved: {stable_filename} ({file_size:,} bytes)")
                
                # Create relative path: assets/images/filename.jpg
                relative_path = f"assets/images/{stable_filename}"
                
                # Update HTML tag with relative path
                img_tag['src'] = relative_path
                # Remove srcset to avoid confusion
                if img_tag.get('srcset'):
                    del img_tag['srcset']
                print(f"       🔄 Rewrote URL to: {relative_path}")
                
                # Track this download
                downloaded_images[absolute_url] = relative_path
                self.stats["assets_downloaded"] += 1
                
            except requests.exceptions.HTTPError as e:
                status = e.response.status_code
                print(f"       ❌ HTTP {status}: {absolute_url[:60]}")
                failed_downloads += 1
                continue
            except Exception as e:
                print(f"       ❌ Error: {str(e)[:60]}")
                failed_downloads += 1
                continue
        
        # MACOS FIX: Save rewritten HTML as binary
        print(f"\n  💾 Saving rewritten HTML...")
        with open(html_path, 'wb') as f:
            html_bytes = str(soup).encode('utf-8')
            f.write(html_bytes)
        
        print(f"  ✅ Archived {len(downloaded_images)} images to assets/images/ directory")
        if failed_downloads > 0:
            print(f"  ⚠️  {failed_downloads} images failed to download")
        print(f"  ✅ Rewrote image URLs to relative paths")
        
        # Verify images directory has files
        if images_dir.exists():
            image_files = list(images_dir.glob("*"))
            print(f"  📊 assets/images/ directory contains {len(image_files)} files")
            if image_files:
                print(f"  📄 Sample filenames:")
                for img_file in image_files[:3]:
                    print(f"     - {img_file.name}")
        else:
            print(f"  ⚠️  WARNING: assets/images/ directory does not exist!")
    
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
                
                # Determine filename with proper extensions
                extension_map = {
                    'pdf': 'pdf',
                    'docx': 'docx',
                    'markdown': 'md',
                    'epub': 'epub',
                    'html': 'html',
                    'odt': 'odt',
                    'txt': 'txt',
                    'jats': 'xml',
                    'latex': 'tex'
                }
                
                ext = extension_map.get(format_name, format_name)
                
                # Special naming for HTML
                if format_name == "html":
                    filename = pub_dir / "index.html"
                elif format_name == "jats":
                    filename = pub_dir / f"{slug}.xml"
                else:
                    filename = pub_dir / f"{slug}.{ext}"
                
                # Download
                success = self.download_file(download_url, filename, format_name)
                
                download_summary[format_name] = {
                    "url": download_url,
                    "local_path": str(filename.relative_to(self.output_dir)),
                    "success": success,
                    "exists": filename.exists()
                }
                
                # If HTML downloaded successfully, archive its assets
                if success and format_name == "html" and filename.exists():
                    try:
                        with open(filename, 'r', encoding='utf-8') as f:
                            html_content = f.read()
                        # Pass slug to the archival function
                        self.archive_html_with_assets(filename, html_content, slug)
                    except Exception as e:
                        print(f"  ⚠️  Could not archive HTML assets: {e}")
                        import traceback
                        traceback.print_exc()
            
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
        print("🍎 macOS USERS: Verifying HTML")
        print("="*70)
        print("To test if images work offline:")
        print("  1. Turn off WiFi")
        print("  2. Open index.html in your browser")
        print("  3. Images should display from assets/images/")


def main():
    print("="*70)
    print("🧪 Single Publication Test Scraper - CLEAN VERSION")
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
    print("  3. Open index.html in a browser WITH WIFI OFF to test")
    print("  4. If everything looks good, ready for full scraper!")


if __name__ == "__main__":
    # Install: pip install requests beautifulsoup4 lxml
    main()