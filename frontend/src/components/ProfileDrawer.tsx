import React, { useEffect, useState } from 'react';
import type { User, InferredAttribute } from '../types';
import { getInferred, deleteInferred, confirmInferred, getSearchHistory, clearSearchHistory } from '../api';

interface Props {
  user: User | null;
  onClose: () => void;
  onLogout: () => void;
}

// Confidence bar: 5 blocks
function ConfBar({ confidence }: { confidence: number }) {
  const filled = Math.round(confidence * 5);
  return (
    <span className="text-xs text-gray-400 font-mono">
      {'█'.repeat(filled)}{'░'.repeat(5 - filled)}
    </span>
  );
}

// Hebrew labels for inferred attributes
const ATTR_LABELS: Record<string, string> = {
  gender: 'מין',
  age_range: 'גיל משוער',
  has_children: 'ילדים',
  child_age_range: 'גיל ילדים',
  lifestyle: 'סגנון חיים',
  price_sensitivity: 'רגישות מחיר',
  occasions: 'אירועים',
  interests: 'תחומי עניין',
};

export default function ProfileDrawer({ user, onClose, onLogout }: Props) {
  const [inferred, setInferred] = useState<InferredAttribute[]>([]);
  const [history, setHistory] = useState<{ message: string; searched_at: string }[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!user) { setLoading(false); return; }
    Promise.all([getInferred(), getSearchHistory()])
      .then(([inf, hist]) => { setInferred(inf); setHistory(hist); })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [user]);

  const handleDeleteInferred = async (id: string) => {
    await deleteInferred(id).catch(() => {});
    setInferred(prev => prev.filter(a => a.id !== id));
  };

  const handleConfirmInferred = async (id: string) => {
    await confirmInferred(id).catch(() => {});
    setInferred(prev => prev.map(a => a.id === id ? { ...a, is_confirmed: true, confidence: 1.0 } : a));
  };

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/40 z-40" onClick={onClose} />

      {/* Drawer */}
      <div className="fixed top-0 right-0 h-full w-80 max-w-full bg-white z-50 shadow-2xl flex flex-col" dir="rtl">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-gray-100">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-blue-600 flex items-center justify-center text-white font-bold">
              {user ? (user.display_name || user.email)[0].toUpperCase() : '?'}
            </div>
            <div>
              <p className="font-medium text-sm">{user?.display_name || user?.email || 'אורח'}</p>
              {user && <p className="text-xs text-gray-400">{user.email}</p>}
            </div>
          </div>
          <div className="flex gap-2">
            {user && (
              <button onClick={onLogout} className="text-xs text-red-500 hover:underline">התנתק</button>
            )}
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
          </div>
        </div>

        {/* Scrollable content */}
        <div className="flex-1 overflow-y-auto p-4 space-y-6">
          {/* Search History */}
          <section>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-semibold text-gray-700">היסטוריית חיפושים</h3>
              {history.length > 0 && (
                <button
                  onClick={async () => { await clearSearchHistory(); setHistory([]); }}
                  className="text-xs text-red-400 hover:underline"
                >
                  נקה
                </button>
              )}
            </div>
            {loading ? (
              <p className="text-xs text-gray-400">טוען...</p>
            ) : history.length === 0 ? (
              <p className="text-xs text-gray-400">אין היסטוריה עדיין</p>
            ) : (
              <ul className="space-y-1">
                {history.slice(0, 10).map((h, i) => (
                  <li key={i} className="text-xs text-gray-600 py-1 border-b border-gray-50">
                    {h.message}
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* Inferred Attributes */}
          <section>
            <h3 className="text-sm font-semibold text-gray-700 mb-2">מה FindMe יודע עליך</h3>
            {loading ? (
              <p className="text-xs text-gray-400">טוען...</p>
            ) : inferred.length === 0 ? (
              <p className="text-xs text-gray-400">עוד לא נאסף מידע</p>
            ) : (
              <ul className="space-y-2">
                {inferred.map(attr => (
                  <li key={attr.id} className={`flex items-center justify-between gap-2 ${attr.confidence < 0.5 ? 'opacity-50' : ''}`}>
                    <div className="flex-1 min-w-0">
                      <span className="text-xs font-medium text-gray-700">
                        {ATTR_LABELS[attr.attribute] || attr.attribute}:
                      </span>
                      <span className="text-xs text-gray-500 mr-1">{attr.value}</span>
                      <ConfBar confidence={attr.confidence} />
                      {attr.confidence < 0.5 && (
                        <p className="text-xs text-gray-400">לא משפיע על חיפושים עד שתאשר</p>
                      )}
                    </div>
                    <div className="flex gap-1 shrink-0">
                      {!attr.is_confirmed && (
                        <button
                          onClick={() => handleConfirmInferred(attr.id)}
                          className="text-green-500 text-xs hover:underline"
                          title="אשר"
                        >✓</button>
                      )}
                      <button
                        onClick={() => handleDeleteInferred(attr.id)}
                        className="text-red-400 text-xs hover:underline"
                        title="מחק"
                      >✗</button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    </>
  );
}
