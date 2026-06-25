import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface Investigation {
  analysis_id: string;
  created_at: string;
  customer_id: string;
  customer_name?: string | null;
  region?: string | null;
  security_status: string;
  risk_score?: string | number | null;
  risk_level?: string | null;
  fraud_probability?: string | number | null;
  summary?: string | null;
}

export interface Reading {
  reading_id: string;
  customer_id: string;
  customer_name?: string | null;
  region?: string | null;
  consumption_kwh: string | number;
  baseline_consumption_kwh: string | number;
  meter_id: string;
  reading_type: string;
  timestamp: string;
}

export interface Customer {
  customer_id: string;
  name: string;
  region: string;
  account_age_days: number;
  meter_trust_score: string | number;
  past_fraud: string | boolean;
  property_type: string;
  baseline_consumption_kwh: number;
}

export interface InvestigationDetail {
  analysis_id: string;
  created_at: string;
  customer_id: string;
  customer_name?: string | null;
  region?: string | null;
  account_age_days?: string | number | null;
  meter_trust_score?: string | number | null;
  past_fraud?: string | boolean | null;
  property_type?: string | null;
  baseline_consumption_kwh?: string | number | null;
  security_status: string;
  risk_score?: string | number | null;
  risk_level?: string | null;
  fraud_probability?: string | number | null;
  summary?: string | null;
  risk_analysis?: string | null;
  compliance_report?: string | null;
  fraud_alert?: string | null;
  reading_json?: string | null;
}

/** Base URL of the read-only API. Same-origin in production (served by FastAPI),
 *  localhost:8000 when running the Angular dev server on :4200.
 *  Override with window.__API_BASE__ if needed. */
const API_BASE =
  (globalThis as any).__API_BASE__ ??
  (typeof location !== 'undefined' && location.port === '4200'
    ? 'http://localhost:8000'
    : '');

@Injectable({ providedIn: 'root' })
export class Api {
  private http = inject(HttpClient);

  investigations(limit = 50): Observable<Investigation[]> {
    return this.http.get<Investigation[]>(`${API_BASE}/api/investigations?limit=${limit}`);
  }

  readings(limit = 50): Observable<Reading[]> {
    return this.http.get<Reading[]>(`${API_BASE}/api/readings/latest?limit=${limit}`);
  }

  customers(): Observable<Customer[]> {
    return this.http.get<Customer[]>(`${API_BASE}/api/customers`);
  }

  investigation(analysisId: string): Observable<InvestigationDetail> {
    return this.http.get<InvestigationDetail>(`${API_BASE}/api/investigation/${encodeURIComponent(analysisId)}`);
  }
}
