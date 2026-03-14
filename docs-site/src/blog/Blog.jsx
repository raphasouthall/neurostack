import { Link } from 'react-router-dom'
import { Nav, Footer } from '../App'
import { posts } from './posts'
import './Blog.css'

/* ═══════════════════════════════════════════════════════════════
   Blog Index — list of all posts
   ═══════════════════════════════════════════════════════════════ */

export default function Blog() {
  return (
    <div className="page">
    <Nav />
    <main className="blog">
      <header className="blog-header">
        <p className="blog-label">Engineering Blog</p>
        <h1 className="blog-title">Notes from the build</h1>
        <p className="blog-subtitle">
          Testing, architecture decisions, and lessons learned while building NeuroStack.
        </p>
      </header>

      <div className="blog-grid">
        {posts.map(post => (
          <article key={post.slug} className="blog-card">
            {post.heroSvg && (
              <Link to={`/blog/${post.slug}`} className="blog-card-hero">
                <img src={post.heroSvg} alt="" loading="lazy" />
              </Link>
            )}
            <div className="blog-card-body">
              <div className="blog-card-meta">
                <time dateTime={post.date}>{formatDate(post.date)}</time>
                <span className="blog-card-dot" aria-hidden="true" />
                <span>{post.readTime}</span>
              </div>
              <h2>
                <Link to={`/blog/${post.slug}`}>{post.title}</Link>
              </h2>
              <p>{post.excerpt}</p>
              <div className="blog-card-tags">
                {post.tags.map(tag => (
                  <span key={tag} className="blog-tag">{tag}</span>
                ))}
              </div>
            </div>
          </article>
        ))}
      </div>
    </main>
    <Footer />
    </div>
  )
}

function formatDate(iso) {
  return new Date(iso + 'T00:00:00').toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  })
}
