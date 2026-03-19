import { useParams, Link, Navigate } from 'react-router-dom'
import { Nav, Footer } from '../App'
import { getPost } from './posts'
import './Blog.css'

/* ═══════════════════════════════════════════════════════════════
   Blog Post — renders structured post content
   ═══════════════════════════════════════════════════════════════ */

export default function BlogPost() {
  const { slug } = useParams()
  const post = getPost(slug)

  if (!post) return <Navigate to="/blog" replace />

  return (
    <div className="page">
    <Nav />
    <article className="blog-post">
      <header className="blog-post-header">
        <Link to="/blog" className="blog-back">&larr; All posts</Link>
        <div className="blog-post-meta">
          <time dateTime={post.date}>{formatDate(post.date)}</time>
          <span className="blog-card-dot" aria-hidden="true" />
          <span>{post.readTime}</span>
          <span className="blog-card-dot" aria-hidden="true" />
          <span>{post.author}</span>
        </div>
        <h1 className="blog-post-title">{post.title}</h1>
        <div className="blog-card-tags">
          {post.tags.map(tag => (
            <span key={tag} className="blog-tag">{tag}</span>
          ))}
        </div>
      </header>

      <div className="blog-post-body">
        {post.sections.map((section, i) => (
          <Section key={i} section={section} />
        ))}
      </div>

      <footer className="blog-post-footer">
        <Link to="/blog" className="blog-back">&larr; Back to blog</Link>
      </footer>
    </article>
    <Footer />
    </div>
  )
}

function Section({ section }) {
  switch (section.type) {
    case 'heading':
      return section.level === 2
        ? <h2 className="blog-h2">{section.content}</h2>
        : <h3 className="blog-h3">{section.content}</h3>

    case 'text':
      return <p className="blog-p">{section.content}</p>

    case 'code':
      return (
        <pre className="blog-code-block">
          <code>{section.content}</code>
        </pre>
      )

    case 'svg':
      return (
        <figure className="blog-figure">
          <img src={section.src} alt={section.alt} loading="lazy" />
          {section.caption && <figcaption>{section.caption}</figcaption>}
        </figure>
      )

    case 'table':
      return (
        <div className="blog-table-wrap">
          <table className="blog-table">
            <thead>
              <tr>
                {section.headers.map((h, i) => <th key={i}>{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {section.rows.map((row, i) => (
                <tr key={i}>
                  {row.map((cell, j) => <td key={j}>{cell}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )

    case 'stats':
      return (
        <div className="blog-stats">
          {section.items.map((item, i) => (
            <div key={i} className="blog-stat">
              <span className="blog-stat-value">{item.value}</span>
              <span className="blog-stat-label">{item.label}</span>
              <span className="blog-stat-detail">{item.detail}</span>
            </div>
          ))}
        </div>
      )

    case 'list':
      return (
        <ul className="blog-list">
          {section.items.map((item, i) => (
            <li key={i}>
              {item.bold && <strong>{item.bold}</strong>}
              {item.text}
            </li>
          ))}
        </ul>
      )

    case 'bugs':
      return (
        <div className="blog-bugs">
          {section.items.map((bug, i) => (
            <div key={i} className={`blog-bug blog-bug--${bug.severity.toLowerCase()}`}>
              <div className="blog-bug-header">
                <span className="blog-bug-severity">{bug.severity}</span>
                <span className="blog-bug-title">{bug.title}</span>
              </div>
              <p>{bug.description}</p>
            </div>
          ))}
        </div>
      )

    default:
      return null
  }
}

function formatDate(iso) {
  return new Date(iso + 'T00:00:00').toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  })
}
