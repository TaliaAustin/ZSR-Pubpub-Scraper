import { chromium } from 'playwright';
import fs from 'fs/promises';
import path from 'path';
import { createWriteStream } from 'fs';
import https from 'https';
import http from 'http';

// Configuration
const CONFIG = {
  baseUrl: 'https://urbanafrica.pubpub.org',
  outputDir: './preserved-pubpub',
  delays: {
    navigation: 2000,
    content: 1000,
    polite: 500
  },
  headless: false,
  userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
  // Only scrape published pubs
  publishedOnly: true
};

// Archive structure
const DIRS = {
  admin: '00_Admin',
  snapshots: '01_Site_Snapshots',
  pubs: '02_Pubs',
  media: '03_Media',
  metadata: '04_Metadata',
  manifests: '05_Manifests'
};

// Utilities
async function ensureDir(dirPath) {
  try {
    await fs.mkdir(dirPath, { recursive: true });
  } catch (error) {
    console.error(`Error creating directory ${dirPath}:`, error.message);
  }
}

async function saveJson(filepath, data) {
  await fs.writeFile(filepath, JSON.stringify(data, null, 2), 'utf-8');
}

function sanitizeFilename(text) {
  return text
    .replace(/[^a-z0-9]/gi, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
    .toLowerCase()
    .substring(0, 100);
}

async function waitForNetworkIdle(page, timeout = 5000) {
  try {
    await page.waitForLoadState('networkidle', { timeout });
  } catch (error) {
    console.log('Network idle timeout - continuing anyway');
  }
}

// Download a file from URL
async function downloadFile(url, filepath) {
  return new Promise((resolve, reject) => {
    const protocol = url.startsWith('https') ? https : http;
    const file = createWriteStream(filepath);
    
    protocol.get(url, (response) => {
      if (response.statusCode === 200) {
        response.pipe(file);
        file.on('finish', () => {
          file.close();
          resolve(filepath);
        });
      } else if (response.statusCode === 301 || response.statusCode === 302) {
        file.close();
        fs.unlink(filepath).catch(() => {});
        downloadFile(response.headers.location, filepath).then(resolve).catch(reject);
      } else {
        file.close();
        fs.unlink(filepath).catch(() => {});
        reject(new Error(`Failed to download: ${response.statusCode}`));
      }
    }).on('error', (err) => {
      file.close();
      fs.unlink(filepath).catch(() => {});
      reject(err);
    });
  });
}

// Convert HTML to Markdown (basic)
function htmlToMarkdown(html) {
  if (!html) return '';
  
  let md = html
    // Headers
    .replace(/<h1[^>]*>(.*?)<\/h1>/gi, '# $1\n\n')
    .replace(/<h2[^>]*>(.*?)<\/h2>/gi, '## $1\n\n')
    .replace(/<h3[^>]*>(.*?)<\/h3>/gi, '### $1\n\n')
    .replace(/<h4[^>]*>(.*?)<\/h4>/gi, '#### $1\n\n')
    // Bold and italic
    .replace(/<strong[^>]*>(.*?)<\/strong>/gi, '**$1**')
    .replace(/<b[^>]*>(.*?)<\/b>/gi, '**$1**')
    .replace(/<em[^>]*>(.*?)<\/em>/gi, '*$1*')
    .replace(/<i[^>]*>(.*?)<\/i>/gi, '*$1*')
    // Links
    .replace(/<a[^>]*href="([^"]*)"[^>]*>(.*?)<\/a>/gi, '[$2]($1)')
    // Paragraphs
    .replace(/<p[^>]*>(.*?)<\/p>/gi, '$1\n\n')
    .replace(/<br\s*\/?>/gi, '\n')
    // Lists
    .replace(/<li[^>]*>(.*?)<\/li>/gi, '- $1\n')
    .replace(/<\/?[uo]l[^>]*>/gi, '\n')
    // Remove remaining HTML tags
    .replace(/<[^>]+>/g, '')
    // Clean up entities
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    // Clean up whitespace
    .replace(/\n{3,}/g, '\n\n')
    .trim();
  
  return md;
}

// Convert HTML to basic JATS XML
function htmlToJATS(pubData) {
  const cleanText = (html) => {
    return html?.replace(/<[^>]+>/g, '').replace(/&nbsp;/g, ' ').trim() || '';
  };

  const authors = pubData.authors.map(author => {
    const names = author.split(' ');
    const surname = names.pop() || '';
    const givenNames = names.join(' ');
    return `      <contrib>
        <name>
          <surname>${surname}</surname>
          <given-names>${givenNames}</given-names>
        </name>
      </contrib>`;
  }).join('\n');

  return `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE article PUBLIC "-//NLM//DTD JATS (Z39.96) Journal Archiving and Interchange DTD v1.2 20190208//EN" "JATS-archivearticle1.dtd">
<article xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:mml="http://www.w3.org/1998/Math/MathML" article-type="research-article">
  <front>
    <article-meta>
      <title-group>
        <article-title>${cleanText(pubData.fullTitle)}</article-title>
      </title-group>
      <contrib-group>
${authors}
      </contrib-group>
      ${pubData.doi ? `<article-id pub-id-type="doi">${pubData.doi}</article-id>` : ''}
      ${pubData.abstract ? `<abstract><p>${cleanText(pubData.abstract)}</p></abstract>` : ''}
      <pub-date>
        <year>${new Date(pubData.date || Date.now()).getFullYear()}</year>
      </pub-date>
    </article-meta>
  </front>
  <body>
    <p>${cleanText(pubData.content)}</p>
  </body>
</article>`;
}

// Step 1: Discover collections
async function discoverCollections(page) {
  console.log('\n=== DISCOVERING COLLECTIONS ===');
  
  await page.goto(CONFIG.baseUrl, { waitUntil: 'domcontentloaded' });
  await waitForNetworkIdle(page);
  await page.waitForTimeout(CONFIG.delays.content);

  const collections = await page.evaluate(() => {
    const results = [];
    
    // Strategy 1: Look for collection links
    const collectionLinks = document.querySelectorAll('a[href*="/collection/"], a[href*="/collections/"]');
    collectionLinks.forEach(link => {
      const href = link.getAttribute('href');
      const title = link.textContent?.trim() || link.getAttribute('title') || '';
      if (href && title && !href.endsWith('/collection/') && !href.endsWith('/collections/')) {
        results.push({
          title,
          url: href.startsWith('http') ? href : window.location.origin + href,
          slug: href.split('/').pop() || href.split('/').slice(-2)[0]
        });
      }
    });

    // Strategy 2: Look in navigation
    const navLinks = document.querySelectorAll('nav a, .nav a, [role="navigation"] a');
    navLinks.forEach(link => {
      const href = link.getAttribute('href');
      const title = link.textContent?.trim() || '';
      if (href && title && href.includes('/') && !href.startsWith('#')) {
        const url = href.startsWith('http') ? href : window.location.origin + href;
        const slug = href.split('/').pop() || 'unknown';
        if (slug && slug !== 'unknown' && !results.some(r => r.slug === slug)) {
          results.push({ title, url, slug });
        }
      }
    });

    // Deduplicate by slug
    const uniqueResults = Array.from(
      new Map(results.map(r => [r.slug, r])).values()
    );

    return uniqueResults;
  });

  console.log(`Found ${collections.length} collections`);
  
  if (collections.length === 0) {
    console.log('\n⚠️  NO COLLECTIONS FOUND - Saving debug info...');
    const debugHtml = await page.content();
    await fs.writeFile(
      path.join(CONFIG.outputDir, DIRS.admin, 'homepage-debug.html'),
      debugHtml
    );
    
    // Take a screenshot
    await page.screenshot({ 
      path: path.join(CONFIG.outputDir, DIRS.admin, 'homepage-screenshot.png'),
      fullPage: true 
    });
    
    console.log(`Saved: ${DIRS.admin}/homepage-debug.html`);
    console.log(`Saved: ${DIRS.admin}/homepage-screenshot.png`);
    console.log('\nPlease check these files and look for collection links manually.');
    console.log('Then we can update the selectors.\n');
  }
  
  collections.forEach((col, idx) => {
    console.log(`  ${idx + 1}. ${col.title} (${col.slug})`);
  });

  return collections;
}

// Step 2: Scrape collection
async function scrapeCollection(page, collection) {
  console.log(`\n--- Scraping Collection: ${collection.title} ---`);
  
  await page.goto(collection.url, { waitUntil: 'domcontentloaded' });
  await waitForNetworkIdle(page);
  await page.waitForTimeout(CONFIG.delays.content);

  const collectionData = await page.evaluate((collectionInfo) => {
    const data = {
      ...collectionInfo,
      scrapedAt: new Date().toISOString(),
      description: '',
      publications: [],
      metadata: {}
    };

    // Get description
    const descSelectors = [
      '.collection-description',
      '[class*="description"]',
      'meta[name="description"]',
      'meta[property="og:description"]'
    ];
    
    for (const selector of descSelectors) {
      const el = document.querySelector(selector);
      if (el) {
        data.description = selector.includes('meta') 
          ? el.getAttribute('content') 
          : el.textContent?.trim();
        if (data.description) break;
      }
    }

    // Find publication links
    const pubLinks = document.querySelectorAll('a[href*="/pub/"]');
    const pubsSet = new Set();

    pubLinks.forEach(link => {
      const href = link.getAttribute('href');
      if (!href || href === '/pub/') return;

      const title = link.textContent?.trim() || 
                   link.getAttribute('title') || 
                   link.querySelector('[class*="title"]')?.textContent?.trim() || 
                   'Untitled';
      
      const url = href.startsWith('http') ? href : window.location.origin + href;
      const slug = href.split('/pub/')[1]?.split('/')[0] || 'unknown';
      
      if (slug !== 'unknown' && !pubsSet.has(slug)) {
        pubsSet.add(slug);
        
        const parent = link.closest('[class*="pub"], [class*="publication"], li, article');
        let authors = '';
        let date = '';
        let isPublished = true; // Assume published unless we find draft indicator
        
        if (parent) {
          const authorEl = parent.querySelector('[class*="author"], .byline');
          const dateEl = parent.querySelector('[class*="date"], time');
          const statusEl = parent.querySelector('[class*="draft"], [class*="status"]');
          
          authors = authorEl?.textContent?.trim() || '';
          date = dateEl?.getAttribute('datetime') || dateEl?.textContent?.trim() || '';
          
          // Check if it's a draft
          if (statusEl && statusEl.textContent?.toLowerCase().includes('draft')) {
            isPublished = false;
          }
        }

        data.publications.push({
          title,
          url,
          slug,
          authors,
          date,
          isPublished
        });
      }
    });

    return data;
  }, collection);

  // Filter for published only if configured
  if (CONFIG.publishedOnly) {
    const originalCount = collectionData.publications.length;
    collectionData.publications = collectionData.publications.filter(p => p.isPublished);
    console.log(`  Found ${collectionData.publications.length} published publications (${originalCount - collectionData.publications.length} drafts filtered out)`);
  } else {
    console.log(`  Found ${collectionData.publications.length} publications`);
  }
  
  return collectionData;
}

// Step 3: Scrape publication with all formats
async function scrapePublication(page, publication, pubDir) {
  console.log(`    Scraping: ${publication.title.substring(0, 50)}...`);
  
  try {
    await page.goto(publication.url, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await waitForNetworkIdle(page);
    await page.waitForTimeout(CONFIG.delays.polite);

    // Extract publication data
    const pubData = await page.evaluate((pubInfo) => {
      const data = {
        ...pubInfo,
        scrapedAt: new Date().toISOString(),
        fullTitle: '',
        content: '',
        contentHtml: '',
        metadata: {},
        authors: [],
        doi: '',
        abstract: '',
        images: []
      };

      // Get full title
      const titleEl = document.querySelector('h1, [class*="pub-title"], .title');
      data.fullTitle = titleEl?.textContent?.trim() || pubInfo.title;

      // Get authors
      const authorEls = document.querySelectorAll('[class*="author"], .byline a, [class*="contributor"]');
      data.authors = Array.from(authorEls).map(el => el.textContent?.trim()).filter(Boolean);

      // Get DOI
      const doiEl = document.querySelector('[class*="doi"], a[href*="doi.org"]');
      if (doiEl) {
        data.doi = doiEl.textContent?.trim() || doiEl.getAttribute('href') || '';
      }

      // Get abstract
      const abstractEl = document.querySelector('[class*="abstract"], .abstract');
      data.abstract = abstractEl?.textContent?.trim() || '';

      // Get main content
      const contentEl = document.querySelector('[class*="pub-body"], [class*="content"], main article, [class*="editor-content"]');
      if (contentEl) {
        data.contentHtml = contentEl.innerHTML || '';
        data.content = contentEl.textContent || '';
      }

      // Get images
      const imgs = document.querySelectorAll('[class*="pub-body"] img, [class*="content"] img, main img');
      data.images = Array.from(imgs).map(img => ({
        src: img.src,
        alt: img.alt || '',
        title: img.title || ''
      }));

      // Meta tags
      const metaTags = document.querySelectorAll('meta');
      metaTags.forEach(meta => {
        const name = meta.getAttribute('name') || meta.getAttribute('property');
        const content = meta.getAttribute('content');
        if (name && content) {
          data.metadata[name] = content;
        }
      });

      return data;
    }, publication);

    // Save HTML snapshot
    const html = await page.content();
    await fs.writeFile(path.join(pubDir, 'snapshot.html'), html, 'utf-8');

    // Generate Markdown
    const markdown = `# ${pubData.fullTitle}\n\n` +
      `**Authors:** ${pubData.authors.join(', ')}\n\n` +
      (pubData.doi ? `**DOI:** ${pubData.doi}\n\n` : '') +
      (pubData.abstract ? `## Abstract\n\n${pubData.abstract}\n\n` : '') +
      `## Content\n\n${htmlToMarkdown(pubData.contentHtml)}`;
    
    await fs.writeFile(path.join(pubDir, 'content.md'), markdown, 'utf-8');

    // Generate JATS XML
    const jatsXml = htmlToJATS(pubData);
    await fs.writeFile(path.join(pubDir, 'content.xml'), jatsXml, 'utf-8');

    // Try to generate PDF (may not work on all pubs)
    try {
      await page.pdf({ 
        path: path.join(pubDir, 'content.pdf'),
        format: 'A4',
        printBackground: true,
        timeout: 30000
      });
      console.log(`      ✓ PDF generated`);
    } catch (error) {
      console.log(`      ⚠ PDF generation failed: ${error.message}`);
    }

    // Download media assets
    const mediaDir = path.join(pubDir, 'media');
    await ensureDir(mediaDir);
    
    const mediaManifest = [];
    for (let i = 0; i < pubData.images.length; i++) {
      const img = pubData.images[i];
      try {
        const ext = path.extname(new URL(img.src).pathname) || '.jpg';
        const filename = `image-${i + 1}${ext}`;
        const filepath = path.join(mediaDir, filename);
        
        await downloadFile(img.src, filepath);
        mediaManifest.push({
          filename,
          originalUrl: img.src,
          alt: img.alt,
          title: img.title
        });
      } catch (error) {
        console.log(`      ⚠ Failed to download image: ${img.src}`);
      }
    }

    if (mediaManifest.length > 0) {
      await saveJson(path.join(mediaDir, 'media-manifest.json'), mediaManifest);
      console.log(`      ✓ Downloaded ${mediaManifest.length} images`);
    }

    // Save publication manifest
    await saveJson(path.join(pubDir, 'publication-manifest.json'), {
      ...pubData,
      contentHtml: undefined, // Don't duplicate in JSON
      formats: {
        markdown: 'content.md',
        jatsXml: 'content.xml',
        pdf: 'content.pdf',
        html: 'snapshot.html'
      },
      media: {
        count: mediaManifest.length,
        manifest: 'media/media-manifest.json'
      }
    });

    return pubData;

  } catch (error) {
    console.error(`    ✗ Error: ${error.message}`);
    return { ...publication, error: error.message };
  }
}

// Main execution
async function main() {
  console.log('Starting PubPub Comprehensive Archiver...');
  console.log(`Target: ${CONFIG.baseUrl}`);
  console.log(`Published only: ${CONFIG.publishedOnly}`);
  
  // Setup directory structure
  await ensureDir(CONFIG.outputDir);
  await ensureDir(path.join(CONFIG.outputDir, DIRS.admin));
  await ensureDir(path.join(CONFIG.outputDir, DIRS.snapshots, 'collections'));
  await ensureDir(path.join(CONFIG.outputDir, DIRS.snapshots, 'pages'));
  await ensureDir(path.join(CONFIG.outputDir, DIRS.pubs));
  await ensureDir(path.join(CONFIG.outputDir, DIRS.media));
  await ensureDir(path.join(CONFIG.outputDir, DIRS.metadata));
  await ensureDir(path.join(CONFIG.outputDir, DIRS.manifests));

  const browser = await chromium.launch({ 
    headless: CONFIG.headless,
    args: ['--disable-blink-features=AutomationControlled']
  });
  
  const context = await browser.newContext({
    userAgent: CONFIG.userAgent,
    viewport: { width: 1920, height: 1080 }
  });
  
  const page = await context.newPage();

  try {
    // Save homepage snapshot
    await page.goto(CONFIG.baseUrl, { waitUntil: 'domcontentloaded' });
    await waitForNetworkIdle(page);
    const homepage = await page.content();
    await fs.writeFile(
      path.join(CONFIG.outputDir, DIRS.snapshots, 'pages', 'homepage.html'),
      homepage
    );

    // Discover collections
    const collections = await discoverCollections(page);

    const globalManifest = {
      scrapedAt: new Date().toISOString(),
      baseUrl: CONFIG.baseUrl,
      publishedOnly: CONFIG.publishedOnly,
      collections: [],
      allPublications: [],
      stats: {
        totalCollections: 0,
        totalPublications: 0,
        publishedPublications: 0
      }
    };

    const allPubsSeen = new Set();

    // Scrape each collection
    for (const collection of collections) {
      await page.waitForTimeout(CONFIG.delays.polite);
      
      const collectionData = await scrapeCollection(page, collection);
      
      // Save collection snapshot
      const collectionSnapshotDir = path.join(
        CONFIG.outputDir,
        DIRS.snapshots,
        'collections',
        sanitizeFilename(collectionData.slug)
      );
      await ensureDir(collectionSnapshotDir);
      
      const collectionHtml = await page.content();
      await fs.writeFile(
        path.join(collectionSnapshotDir, 'collection.html'),
        collectionHtml
      );

      // Save collection manifest
      await saveJson(
        path.join(collectionSnapshotDir, 'collection-manifest.json'),
        collectionData
      );

      // Scrape all publications in this collection
      const pubsToTest = collectionData.publications.slice(0, 2); // TEST MODE: Only 2 per collection
      console.log(`  TEST MODE: Scraping ${pubsToTest.length} of ${collectionData.publications.length} publications...`);
      
      for (const pub of pubsToTest) {
        await page.waitForTimeout(CONFIG.delays.polite);
        
        // Create pub directory
        const pubDir = path.join(
          CONFIG.outputDir,
          DIRS.pubs,
          sanitizeFilename(pub.slug)
        );
        await ensureDir(pubDir);
        
        // Scrape publication
        const pubData = await scrapePublication(page, pub, pubDir);
        
        // Track all pubs
        if (!allPubsSeen.has(pub.slug)) {
          allPubsSeen.add(pub.slug);
          globalManifest.allPublications.push({
            slug: pub.slug,
            title: pub.title,
            collections: [collectionData.slug]
          });
        } else {
          // Pub appears in multiple collections
          const existingPub = globalManifest.allPublications.find(p => p.slug === pub.slug);
          if (existingPub) {
            existingPub.collections.push(collectionData.slug);
          }
        }
      }

      globalManifest.collections.push({
        slug: collectionData.slug,
        title: collectionData.title,
        description: collectionData.description,
        publicationCount: collectionData.publications.length
      });
    }

    globalManifest.stats.totalCollections = collections.length;
    globalManifest.stats.totalPublications = allPubsSeen.size;
    globalManifest.stats.publishedPublications = CONFIG.publishedOnly ? allPubsSeen.size : -1;

    // Save global manifest
    await saveJson(
      path.join(CONFIG.outputDir, DIRS.manifests, 'global-manifest.json'),
      globalManifest
    );

    // Create validation report
    const validationReport = {
      generatedAt: new Date().toISOString(),
      status: 'complete',
      collections: {
        expected: collections.length,
        scraped: globalManifest.collections.length,
        complete: collections.length === globalManifest.collections.length
      },
      publications: {
        total: globalManifest.stats.totalPublications,
        withPDF: 0, // Could count PDFs
        withMedia: 0 // Could count media
      }
    };

    await saveJson(
      path.join(CONFIG.outputDir, DIRS.manifests, 'validation-report.json'),
      validationReport
    );

    // Save run log
    await saveJson(
      path.join(CONFIG.outputDir, DIRS.admin, 'scrape-log.json'),
      {
        completedAt: new Date().toISOString(),
        config: CONFIG,
        stats: globalManifest.stats
      }
    );

    console.log('\n=== ARCHIVING COMPLETE ===');
    console.log(`Collections: ${globalManifest.stats.totalCollections}`);
    console.log(`Publications: ${globalManifest.stats.totalPublications}`);
    console.log(`Output: ${CONFIG.outputDir}`);
    console.log(`\nStructure:`);
    console.log(`  ${DIRS.admin}/ - Run logs and configuration`);
    console.log(`  ${DIRS.snapshots}/ - HTML snapshots of collections and pages`);
    console.log(`  ${DIRS.pubs}/ - All publications with multiple formats`);
    console.log(`  ${DIRS.manifests}/ - Master manifests and validation`);

  } catch (error) {
    console.error('Fatal error:', error);
    
    // Save error log
    await saveJson(
      path.join(CONFIG.outputDir, DIRS.admin, 'error-log.json'),
      {
        timestamp: new Date().toISOString(),
        error: error.message,
        stack: error.stack
      }
    );
  } finally {
    await browser.close();
  }
}

main().catch(console.error);