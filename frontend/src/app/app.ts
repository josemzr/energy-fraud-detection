import { Component, computed, inject, signal, OnInit } from '@angular/core';
import { DecimalPipe, DatePipe } from '@angular/common';
import { Api, Investigation, Reading, InvestigationDetail } from './api';

@Component({
  selector: 'app-root',
  imports: [DecimalPipe, DatePipe],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App implements OnInit {
  private api = inject(Api);

  readonly investigations = signal<Investigation[]>([]);
  readonly readings = signal<Reading[]>([]);
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);

  // Detail view
  readonly detail = signal<InvestigationDetail | null>(null);
  readonly detailLoading = signal(false);

  // --- KPIs -----------------------------------------------------------------
  readonly total = computed(() => this.investigations().length);
  readonly blocked = computed(
    () => this.investigations().filter((i) => i.security_status === 'BLOCKED').length,
  );
  readonly highRisk = computed(
    () => this.investigations().filter((i) => (i.risk_level || '').toLowerCase() === 'high').length,
  );
  readonly avgRisk = computed(() => {
    const xs = this.investigations()
      .map((i) => Number(i.risk_score))
      .filter((n) => !isNaN(n) && n > 0);
    return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0;
  });

  readonly byLevel = computed(() => {
    const c = { High: 0, Medium: 0, Low: 0 };
    for (const i of this.investigations()) {
      const l = (i.risk_level || '').toLowerCase();
      if (l === 'high') c.High++;
      else if (l === 'medium') c.Medium++;
      else if (l === 'low') c.Low++;
    }
    return c;
  });

  readonly byStatus = computed(() => {
    const c = { CLEAN: 0, BLOCKED: 0 };
    for (const i of this.investigations()) {
      if (i.security_status === 'BLOCKED') c.BLOCKED++;
      else c.CLEAN++;
    }
    return c;
  });

  ngOnInit(): void {
    this.refresh();
  }

  refresh(): void {
    this.loading.set(true);
    this.error.set(null);
    let pending = 2;
    const done = () => {
      if (--pending === 0) this.loading.set(false);
    };
    this.api.investigations().subscribe({
      next: (rows) => this.investigations.set(rows),
      error: () => {
        this.error.set('No se pudo cargar las investigaciones. ¿Está el API en http://localhost:8000?');
        done();
      },
      complete: done,
    });
    this.api.readings().subscribe({
      next: (rows) => this.readings.set(rows),
      error: () => done(),
      complete: done,
    });
  }

  // --- view helpers ---------------------------------------------------------
  num(v: string | number | null | undefined): number {
    const n = Number(v);
    return isNaN(n) ? 0 : n;
  }

  initials(name?: string | null, id?: string): string {
    const src = (name || id || '?').trim();
    const parts = src.split(/\s+/);
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
    return src.slice(0, 2).toUpperCase();
  }

  avatarColor(key: string): string {
    const colors = ['#6366f1', '#0ea5e9', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#14b8a6', '#ec4899'];
    let h = 0;
    for (const ch of key) h = (h * 31 + ch.charCodeAt(0)) % colors.length;
    return colors[h];
  }

  ratio(r: Reading): number {
    const base = this.num(r.baseline_consumption_kwh);
    return base ? this.num(r.consumption_kwh) / base : 0;
  }

  flagged(r: Reading): boolean {
    return this.ratio(r) >= 1.5;
  }

  // --- detail view ----------------------------------------------------------
  open(inv: Investigation): void {
    this.detailLoading.set(true);
    this.detail.set(null);
    this.api.investigation(inv.analysis_id).subscribe({
      next: (d) => {
        this.detail.set(d);
        this.detailLoading.set(false);
      },
      error: () => {
        this.error.set('No se pudo cargar el detalle de la investigación.');
        this.detailLoading.set(false);
      },
    });
  }

  close(): void {
    this.detail.set(null);
  }

  shortId(id: string): string {
    return id ? id.slice(0, 8).toUpperCase() : '';
  }

  isTrue(v: string | boolean | null | undefined): boolean {
    return v === true || v === 'true' || v === 'True' || v === '1';
  }

  /** Parse the stored reading_json into an object for the Reading Information card. */
  reading(d: InvestigationDetail): Record<string, any> {
    if (!d.reading_json) return {};
    try {
      return JSON.parse(d.reading_json);
    } catch {
      return {};
    }
  }

  detailRatio(d: InvestigationDetail): number {
    const r = this.reading(d);
    const base = this.num(r['baseline_consumption_kwh'] ?? d.baseline_consumption_kwh);
    const cons = this.num(r['consumption_kwh']);
    return base ? cons / base : 0;
  }

  /** Parse the fraud-alert text into a decision action keyword. */
  action(d: InvestigationDetail): string {
    if (d.security_status === 'BLOCKED') return 'BLOCK & REVIEW';
    const t = (d.fraud_alert || '').toUpperCase();
    for (const a of ['BLOCK & INVESTIGATE', 'BLOCK', 'INVESTIGATE', 'MONITOR', 'ALLOW']) {
      if (t.includes(a)) return a;
    }
    return '—';
  }

  actionClass(d: InvestigationDetail): string {
    const a = this.action(d);
    if (a.includes('BLOCK')) return 'act-block';
    if (a.includes('INVESTIGATE')) return 'act-investigate';
    if (a.includes('MONITOR')) return 'act-monitor';
    if (a.includes('ALLOW')) return 'act-allow';
    return 'act-monitor';
  }

  /** Derive analyst-facing risk factors (amber chips) from the case data. */
  riskFactors(d: InvestigationDetail): string[] {
    const f: string[] = [];
    if (d.security_status === 'BLOCKED') {
      f.push('Prompt-injection attempt blocked by Prompt Shields');
      f.push('Reading data held for human review');
      return f;
    }
    const r = this.reading(d);
    const ratio = this.detailRatio(d);
    if (ratio >= 2) f.push('Consumption more than 2× the baseline');
    else if (ratio >= 1.3) f.push('Consumption above baseline');
    if (this.num(d.meter_trust_score) > 0 && this.num(d.meter_trust_score) < 0.3)
      f.push('Low meter trust score');
    if (this.num(d.account_age_days) > 0 && this.num(d.account_age_days) < 30)
      f.push('New account within high-risk window');
    if (this.isTrue(d.past_fraud)) f.push('Prior fraud history');
    if (this.num(d.fraud_probability) >= 0.8) f.push('High model fraud probability');
    if ((d.risk_level || '').toLowerCase() === 'high') f.push('High overall risk score');
    if (this.num(r['consumption_kwh']) >= 1000) f.push('Consumption over high-usage threshold');
    if (f.length === 0) f.push('No major risk factors detected');
    return f;
  }
}
