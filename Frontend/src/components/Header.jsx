import { NavLink } from 'react-router-dom'

const LINKS = [
  { to: '/', label: 'Agent' },
  { to: '/supervisor', label: 'Supervisor' },
  { to: '/analytics', label: 'Analytics' },
]

export function Header({ children }) {
  return (
    <header className="border-b border-gray-200 px-6 py-3 flex items-center justify-between bg-white">
      <div className="flex items-center gap-6">
        <div className="flex items-center gap-3">
          <div className="w-7 h-7 rounded-lg bg-violet-600 flex items-center justify-center">
            <svg className="w-4 h-4 text-white" fill="currentColor" viewBox="0 0 24 24">
              <path d="M12 1a4 4 0 0 1 4 4v6a4 4 0 0 1-8 0V5a4 4 0 0 1 4-4zm-7 10a1 1 0 0 1 1 1 6 6 0 1 0 12 0 1 1 0 0 1 2 0 8 8 0 0 1-7 7.938V21h2a1 1 0 0 1 0 2H9a1 1 0 0 1 0-2h2v-2.062A8 8 0 0 1 4 12a1 1 0 0 1 1-1z" />
            </svg>
          </div>
          <span className="font-display font-semibold text-lg tracking-tight">VoiceIQ</span>
        </div>
        <nav className="flex items-center gap-1">
          {LINKS.map(link => (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.to === '/'}
              className={({ isActive }) =>
                `px-3 py-1.5 rounded-md text-sm transition-colors ${
                  isActive ? 'bg-violet-50 text-violet-700 font-medium' : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
                }`}
            >
              {link.label}
            </NavLink>
          ))}
        </nav>
      </div>
      <div className="flex items-center gap-3">
        {children}
        <a href="/docs" target="_blank" rel="noreferrer" className="text-xs text-gray-600 hover:text-violet-600 transition-colors font-mono">
          API docs ↗
        </a>
      </div>
    </header>
  )
}
