import PropTypes from 'prop-types';
import { Button } from '@/shared/components/Button/Button';
import { EmptyState } from '@/shared/components/EmptyState/EmptyState';
import { Spinner } from '@/shared/components/Spinner/Spinner';
import styles from './Admin.module.css';

/** Column = { key, label, render?(row) }. `actions(row)` renders the trailing cell. */
export function DataTable({ columns, rows, rowKey = 'id', loading, empty = 'Kayıt yok', actions }) {
  if (loading) return <Spinner />;
  if (!rows?.length) return <EmptyState title={empty} />;
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            {columns.map((c) => <th key={c.key} scope="col">{c.label}</th>)}
            {actions && <th scope="col"><span className="visually-hidden">İşlemler</span></th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row[rowKey]}>
              {columns.map((c) => <td key={c.key}>{c.render ? c.render(row) : (row[c.key] ?? '—')}</td>)}
              {actions && <td><div className={styles.actions}>{actions(row)}</div></td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

DataTable.propTypes = {
  columns: PropTypes.arrayOf(PropTypes.shape({ key: PropTypes.string.isRequired, label: PropTypes.string.isRequired, render: PropTypes.func })).isRequired,
  rows: PropTypes.array,
  rowKey: PropTypes.string,
  loading: PropTypes.bool,
  empty: PropTypes.string,
  actions: PropTypes.func,
};

export function Badge({ ok, children }) {
  return <span className={`${styles.badge} ${ok === true ? styles.ok : ok === false ? styles.bad : ''}`}>{children}</span>;
}
Badge.propTypes = { ok: PropTypes.bool, children: PropTypes.node };

export function Pager({ page, perPage, total, onPage }) {
  const pages = Math.max(1, Math.ceil(total / perPage));
  return (
    <div className={styles.pager}>
      <Button variant="ghost" size="sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>‹ Önceki</Button>
      <span>{page} / {pages} · {total} kayıt</span>
      <Button variant="ghost" size="sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>Sonraki ›</Button>
    </div>
  );
}
Pager.propTypes = { page: PropTypes.number.isRequired, perPage: PropTypes.number.isRequired, total: PropTypes.number.isRequired, onPage: PropTypes.func.isRequired };

