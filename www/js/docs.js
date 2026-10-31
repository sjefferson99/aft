// Renders the Markdown guides in /docs/ into docs.html. The same files are the
// repo docs, so anything here must keep them readable on GitHub as well: links
// between guides stay as relative .md links and are rewritten to page anchors.

const DOCS_PATH = '/docs/';
const DOC_FILES = ['README.md', 'user-guide.md', 'administration.md'];

// Matches GitHub's heading anchors, so a link works on both.
function headingSlug(text) {
  return text.trim().toLowerCase()
    .replace(/[^\p{L}\p{N}\s_-]/gu, '')
    .replace(/\s/g, '-');
}

async function loadGuide(file) {
  const response = await fetch(`${DOCS_PATH}${file}`, { cache: 'no-cache' });
  if (!response.ok) {
    throw new Error(`Could not load ${file}: HTTP ${response.status}`);
  }

  const html = marked.parse(await response.text());
  return DOMPurify.sanitize(html, { RETURN_DOM_FRAGMENT: true });
}

// Splits a guide into a title and one panel per H2, adding each heading's
// anchor. Returns the guide's title for the table of contents.
function appendGuide(fragment, container) {
  const guide = { title: null, sections: [] };
  let panel = null;

  Array.from(fragment.childNodes).forEach((node) => {
    if (node.nodeName === 'H1') {
      node.id = headingSlug(node.textContent);
      node.classList.add('docs-guide-title');
      guide.title = node;
      container.appendChild(node);
      panel = null;
      return;
    }

    if (node.nodeName === 'H2' || !panel) {
      if (node.nodeType === Node.TEXT_NODE && !node.textContent.trim()) {
        return;
      }
      panel = document.createElement('section');
      panel.className = 'docs-section';
      container.appendChild(panel);
    }

    if (node.nodeName === 'H2') {
      guide.sections.push(node);
    }
    panel.appendChild(node);
  });

  return guide;
}

function addHeadingAnchors(container) {
  container.querySelectorAll('h2, h3, h4').forEach((heading) => {
    heading.id = headingSlug(heading.textContent);
  });
}

function fixLinksAndImages(container, fileAnchors) {
  const docsUrl = new URL(DOCS_PATH, window.location.origin);

  container.querySelectorAll('a[href]').forEach((link) => {
    const href = link.getAttribute('href');
    const guideLink = href.match(/^(?:\.\/)?([\w-]+\.md)(#.*)?$/);

    if (guideLink) {
      link.setAttribute('href', guideLink[2] || `#${fileAnchors[guideLink[1]]}`);
    } else if (/^https?:/i.test(href)) {
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
    }
  });

  container.querySelectorAll('img').forEach((image) => {
    image.src = new URL(image.getAttribute('src'), docsUrl).pathname;
  });

  // Wide tables scroll inside their panel instead of widening a phone screen.
  container.querySelectorAll('table').forEach((table) => {
    const wrapper = document.createElement('div');
    wrapper.className = 'docs-table-scroll';
    table.replaceWith(wrapper);
    wrapper.appendChild(table);
  });
}

function buildToc(toc, guides) {
  const heading = document.createElement('h2');
  heading.textContent = 'Table of Contents';
  toc.appendChild(heading);

  guides.forEach((guide) => {
    const group = document.createElement('div');
    group.className = 'docs-toc-group';

    const title = document.createElement('a');
    title.className = 'docs-toc-guide';
    title.href = `#${guide.title.id}`;
    title.textContent = guide.title.textContent;
    group.appendChild(title);

    const list = document.createElement('ul');
    guide.sections.forEach((section) => {
      const item = document.createElement('li');
      const link = document.createElement('a');
      link.href = `#${section.id}`;
      link.textContent = section.textContent;
      item.appendChild(link);
      list.appendChild(item);
    });
    group.appendChild(list);
    toc.appendChild(group);
  });
}

// The anchor doesn't exist until the guides render, so the browser can't jump
// to it. Wait for images too, or they push the heading back off screen.
async function scrollToHash(container) {
  const target = window.location.hash
    ? document.getElementById(decodeURIComponent(window.location.hash.slice(1)))
    : null;
  if (!target) {
    return;
  }

  await Promise.allSettled(Array.from(container.querySelectorAll('img')).map((image) => image.decode()));
  target.scrollIntoView();
}

async function renderDocs() {
  const toc = document.getElementById('docs-toc');
  const content = document.getElementById('docs-content');

  try {
    const fragments = await Promise.all(DOC_FILES.map(loadGuide));
    const fileAnchors = {};
    const guides = fragments.map((fragment, index) => {
      const guide = appendGuide(fragment, content);
      fileAnchors[DOC_FILES[index]] = guide.title.id;
      return guide;
    });

    addHeadingAnchors(content);
    fixLinksAndImages(content, fileAnchors);
    buildToc(toc, guides);
    toc.hidden = false;
    await scrollToHash(content);
  } catch (error) {
    console.error('Failed to load the docs:', error);
    content.replaceChildren();
    const message = document.createElement('section');
    message.className = 'docs-section';
    message.textContent = 'The docs could not be loaded. Refresh the page to try again.';
    content.appendChild(message);
  }
}

renderDocs();
