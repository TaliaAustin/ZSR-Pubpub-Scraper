"""
PubPub Export URL Testing Script
Tests whether PubPub's export endpoints work for a given publication
Run this before the full scraper to verify functionality
"""

import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urlparse
from datetime import datetime
import json

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

class PubPubTester:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip('/')
        self.test_results = {
            "test_date": datetime.now().isoformat(),
            "base_url": base_url,
            "sitemap_test": {},
            "publication_tests": []
        }
    
    def test_sitemap_access(self):
        """Test 1: Can we access the sitemap?"""
        print("\n" + "="*60)
        print("TEST 1: Sitemap Accessibility")
        print("="*60)
        
        sitemap_url = f"{self.base_url}/sitemap.xml"
        all_urls = []
        
        def fetch_sitemap_recursive(url, depth=0):
            """Recursively fetch sitemaps"""
            nonlocal all_urls
            
            if depth > 3:  # Prevent infinite recursion
                return
            
            indent = "   " * depth
            print(f"{indent}Fetching: {url}")
            
            try:
                response = requests.get(url, headers=HEADERS, timeout=10)
                response.raise_for_status()
                
                soup = BeautifulSoup(response.content, 'xml')
                
                # Check if it's a sitemap index
                if soup.find("sitemapindex"):
                    print(f"{indent}   → Sitemap Index found")
                    sitemap_tags = soup.find_all("sitemap")
                    print(f"{indent}   → Contains {len(sitemap_tags)} sub-sitemaps")
                    
                    for sitemap_tag in sitemap_tags:
                        loc = sitemap_tag.find("loc")
                        if loc:
                            fetch_sitemap_recursive(loc.text.strip(), depth + 1)
                else:
                    # Regular sitemap with URLs
                    locs = soup.find_all("loc")
                    print(f"{indent}   → Found {len(locs)} URLs")
                    
                    for loc in locs:
                        url_text = loc.text.strip()
                        # Skip the base URL itself
                        if url_text.strip("/") != self.base_url.strip("/"):
                            all_urls.append(url_text)
                            
            except Exception as e:
                print(f"{indent}   ❌ Error: {e}")
        
        try:
            fetch_sitemap_recursive(sitemap_url)
            
            # Filter for publication URLs
            pub_urls = [url for url in all_urls if "/pub/" in url]
            
            self.test_results["sitemap_test"] = {
                "accessible": True,
                "url": sitemap_url,
                "total_urls": len(all_urls),
                "publication_urls": len(pub_urls)
            }
            
            print(f"\n✅ Sitemap crawl complete")
            print(f"   Total URLs found: {len(all_urls)}")
            print(f"   Publication URLs: {len(pub_urls)}")
            
            if pub_urls:
                print(f"\n   Sample publication URLs:")
                for url in pub_urls[:3]:
                    print(f"   - {url}")
            
            return pub_urls
            
        except requests.exceptions.RequestException as e:
            self.test_results["sitemap_test"] = {
                "accessible": False,
                "error": str(e)
            }
            print(f"❌ Sitemap not accessible: {e}")
            return []
    
    def test_publication_page(self, pub_url):
        """Test 2: Can we access a publication page and extract metadata?"""
        print("\n" + "="*60)
        print(f"TEST 2: Publication Page Analysis")
        print("="*60)
        print(f"URL: {pub_url}")
        
        test_result = {
            "url": pub_url,
            "accessible": False,
            "metadata": {},
            "download_links_found": [],
            "export_endpoints": {}
        }
        
        try:
            response = requests.get(pub_url, headers=HEADERS, timeout=15)
            response.raise_for_status()
            
            test_result["accessible"] = True
            test_result["status_code"] = response.status_code
            test_result["final_url"] = response.url
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extract metadata
            print("\n📄 Metadata Extraction:")
            
            # Title
            title_meta = soup.find("meta", attrs={"name": "citation_title"})
            title = title_meta['content'] if title_meta else (soup.title.text if soup.title else "Unknown")
            test_result["metadata"]["title"] = title
            print(f"   Title: {title}")
            
            # Authors
            authors = [tag['content'] for tag in soup.find_all("meta", attrs={"name": "citation_author"})]
            test_result["metadata"]["authors"] = authors
            if authors:
                print(f"   Authors: {', '.join(authors)}")
            else:
                print(f"   Authors: None found")
            
            # Date
            date_meta = soup.find("meta", attrs={"name": "citation_publication_date"})
            pub_date = date_meta['content'] if date_meta else "Unknown"
            test_result["metadata"]["publication_date"] = pub_date
            print(f"   Date: {pub_date}")
            
            # Find explicit download links
            print("\n🔗 Explicit Download Links on Page:")
            download_links = []
            for link in soup.find_all('a', href=True):
                href = link['href']
                link_text = link.get_text(strip=True)
                
                # Check for file extensions
                if any(ext in href.lower() for ext in ['.pdf', '.docx', '.epub', '.xml', 'download']):
                    download_links.append({
                        "text": link_text,
                        "href": href,
                        "absolute_url": requests.compat.urljoin(self.base_url, href)
                    })
            
            test_result["download_links_found"] = download_links
            
            if download_links:
                for link in download_links[:5]:  # Show first 5
                    print(f"   - {link['text']}: {link['href']}")
            else:
                print("   No explicit download links found (will test deterministic URLs)")
            
            return test_result
            
        except requests.exceptions.RequestException as e:
            test_result["error"] = str(e)
            print(f"❌ Cannot access publication page: {e}")
            return test_result
    
    def test_export_endpoints(self, pub_url):
        """Test 3: Test PubPub's deterministic export endpoints"""
        print("\n" + "="*60)
        print("TEST 3: Export Endpoint Testing")
        print("="*60)
        
        # Extract canonical path and slug
        final_url = pub_url
        try:
            response = requests.head(pub_url, headers=HEADERS, timeout=10, allow_redirects=True)
            final_url = response.url
        except:
            pass
        
        canonical_path = re.sub(r'/release/\d+$', '', urlparse(final_url).path.strip("/"))
        slug_match = re.search(r'/pub/([^/]+)', canonical_path)
        
        if not slug_match:
            print("❌ Cannot extract publication slug from URL")
            return {}
        
        slug = slug_match.group(1)
        print(f"Publication slug: {slug}")
        
        # Test various export formats
        formats = ['pdf', 'docx', 'epub', 'markdown', 'html', 'jats']
        base_download_url = f"{self.base_url}/{canonical_path}/download"
        
        results = {}
        print(f"\nTesting export URLs: {base_download_url}/[format]")
        print("-" * 60)
        
        for fmt in formats:
            export_url = f"{base_download_url}/{fmt}"
            
            try:
                # Use HEAD request to check availability without downloading
                response = requests.head(export_url, headers=HEADERS, timeout=10, allow_redirects=True)
                
                status_code = response.status_code
                available = status_code == 200
                content_type = response.headers.get('content-type', 'unknown')
                content_length = response.headers.get('content-length', 'unknown')
                
                results[fmt] = {
                    "url": export_url,
                    "available": available,
                    "status_code": status_code,
                    "content_type": content_type,
                    "content_length": content_length
                }
                
                if available:
                    size_kb = int(content_length) // 1024 if content_length != 'unknown' else '?'
                    print(f"✅ {fmt.upper():10} - Available ({size_kb} KB) - {content_type}")
                else:
                    print(f"❌ {fmt.upper():10} - Not available (HTTP {status_code})")
                    
            except requests.exceptions.RequestException as e:
                results[fmt] = {
                    "url": export_url,
                    "available": False,
                    "error": str(e)
                }
                print(f"❌ {fmt.upper():10} - Error: {e}")
        
        return results
    
    def test_asset_download(self, asset_url):
        """Test 4: Test downloading an actual asset"""
        print("\n" + "="*60)
        print("TEST 4: Asset Download Test")
        print("="*60)
        
        if not asset_url:
            print("⚠️  No asset URL provided, skipping")
            return None
        
        print(f"Testing download from: {asset_url}")
        
        try:
            response = requests.get(asset_url, headers=HEADERS, timeout=30, stream=True)
            response.raise_for_status()
            
            # Get first chunk to verify
            first_chunk = next(response.iter_content(chunk_size=1024))
            
            result = {
                "url": asset_url,
                "success": True,
                "status_code": response.status_code,
                "content_type": response.headers.get('content-type'),
                "content_length": response.headers.get('content-length'),
                "first_bytes": len(first_chunk)
            }
            
            print(f"✅ Download successful")
            print(f"   Content-Type: {result['content_type']}")
            print(f"   Size: {result['content_length']} bytes")
            print(f"   First chunk: {result['first_bytes']} bytes received")
            
            return result
            
        except requests.exceptions.RequestException as e:
            result = {
                "url": asset_url,
                "success": False,
                "error": str(e)
            }
            print(f"❌ Download failed: {e}")
            return result
    
    def run_full_test(self, test_pub_url=None):
        """Run complete test suite"""
        print("\n" + "="*70)
        print("🧪 PubPub Export Testing Suite")
        print("="*70)
        print(f"Testing site: {self.base_url}")
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        # Test 1: Sitemap
        sample_urls = self.test_sitemap_access()
        
        # Determine which publication to test
        if test_pub_url:
            pub_to_test = test_pub_url
        elif sample_urls:
            pub_to_test = sample_urls[0]
            print(f"\n💡 Using first publication from sitemap: {pub_to_test}")
        else:
            print("\n❌ No publication URL available for testing")
            print("   Please provide a publication URL manually")
            return
        
        # Test 2: Publication page
        pub_result = self.test_publication_page(pub_to_test)
        self.test_results["publication_tests"].append(pub_result)
        
        # Test 3: Export endpoints
        export_results = self.test_export_endpoints(pub_to_test)
        if pub_result.get("accessible"):
            pub_result["export_endpoints"] = export_results
        
        # Test 4: Try downloading one available format
        available_formats = [fmt for fmt, data in export_results.items() 
                           if data.get("available")]
        
        if available_formats:
            test_format = available_formats[0]
            test_url = export_results[test_format]["url"]
            download_result = self.test_asset_download(test_url)
            pub_result["sample_download"] = download_result
        
        # Summary
        self.print_summary(export_results)
        
        # Save results
        self.save_results()
    
    def print_summary(self, export_results):
        """Print test summary"""
        print("\n" + "="*70)
        print("📊 TEST SUMMARY")
        print("="*70)
        
        available = [fmt for fmt, data in export_results.items() if data.get("available")]
        unavailable = [fmt for fmt, data in export_results.items() if not data.get("available")]
        
        print(f"\n✅ Available formats ({len(available)}):")
        for fmt in available:
            print(f"   - {fmt.upper()}")
        
        if unavailable:
            print(f"\n❌ Unavailable formats ({len(unavailable)}):")
            for fmt in unavailable:
                print(f"   - {fmt.upper()}")
        
        print("\n" + "="*70)
        print("💡 RECOMMENDATIONS:")
        print("="*70)
        
        if len(available) >= 3:
            print("✅ Good coverage! Multiple export formats available.")
            print("   Your scraper should work well with this PubPub instance.")
        elif len(available) >= 1:
            print("⚠️  Limited formats available.")
            print("   Consider focusing on available formats in your scraper.")
        else:
            print("❌ No export formats available via deterministic URLs.")
            print("   You may need to:")
            print("   1. Look for explicit download links on publication pages")
            print("   2. Check if publications are published/released")
            print("   3. Verify the URL pattern is correct")
        
        print("\n📝 Next steps:")
        print("   1. Review the test results saved to 'test_results.json'")
        print("   2. Adjust your scraper to focus on available formats")
        print("   3. Test with 2-3 more publications to verify consistency")
    
    def save_results(self):
        """Save test results to JSON file"""
        output_file = "test_results.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(self.test_results, f, indent=4, ensure_ascii=False)
        print(f"\n💾 Full test results saved to: {output_file}")


def main():
    print("="*70)
    print("🧪 PubPub Export URL Testing Script")
    print("="*70)
    print("\nThis script will test:")
    print("  1. Sitemap accessibility")
    print("  2. Publication metadata extraction")
    print("  3. Export endpoint availability (PDF, DOCX, EPUB, etc.)")
    print("  4. Actual file download capability")
    
    # Get user input
    print("\n" + "-"*70)
    base_url = input("Enter your PubPub base URL (e.g., https://urbanafrica.pubpub.org): ").strip()
    
    if not base_url.startswith('http'):
        base_url = 'https://' + base_url
    
    print("\nOptional: Provide a specific publication URL to test")
    print("(Leave blank to auto-detect from sitemap)")
    test_pub = input("Publication URL (or press Enter to skip): ").strip() or None
    
    # Run tests
    tester = PubPubTester(base_url)
    tester.run_full_test(test_pub)
    
    print("\n" + "="*70)
    print("✅ Testing Complete!")
    print("="*70)


if __name__ == "__main__":
    # Installation: pip install requests beautifulsoup4 lxml
    main()