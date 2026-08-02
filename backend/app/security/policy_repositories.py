"""Authoritative PostgreSQL adapters for Milestone 5.0E Step 10."""

from __future__ import annotations

import enum
import hashlib
import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.exc import (
    DataError, DisconnectionError, IntegrityError, InterfaceError, OperationalError,
    SQLAlchemyError, TimeoutError as SqlAlchemyTimeoutError,
)

from app.models.analysis_run_scope_claim import AnalysisRunScopeClaim
from app.models.bulk_upload_batch import BulkUploadBatch
from app.models.company import Company
from app.models.financial_analysis_result import FinancialAnalysisResult
from app.models.financial_document import FinancialDocument
from app.models.financial_period import FinancialPeriod
from app.models.orchestration_persistence import OrchestrationEngineExecution, OrchestrationRun
from app.models.security import (
    SecurityMembership, SecurityMembershipRole, SecurityPermission, SecurityRole,
    SecurityRolePermission, SecurityTenant,
)
from app.security.authorization_policy import (
    EffectivePermissionSet, PolicyMaterializationRequest, PolicyExistenceHiding,
    PolicyRepositoryError, PolicyRepositoryErrorCode, PolicyScopeType,
    ResolvedPolicyRole, ResourceOwnershipState, ResourceSecurityScope,
    ResourceSecurityVersionCodec,
)
from app.security.contracts import PERMISSION_REGISTRY_VERSION, IdentityKind


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("invalid datetime")
    return value.astimezone(timezone.utc)


def _enum(value: object) -> enum.Enum:
    raw = value.value if isinstance(value, enum.Enum) else str(value)
    return enum.Enum("CanonicalPolicyValue", {"VALUE": raw}).VALUE


def _hex(value: str | None) -> bytes | None:
    if value is None: return None
    return bytes.fromhex(value)


class _PostgresAdapter:
    def __init__(self, session_factory, *, statement_timeout_seconds: float = 2.0) -> None:
        if not 0 < statement_timeout_seconds <= 3: raise ValueError("policy timeout must be in (0, 3]")
        self._sessions=session_factory; self._timeout_ms=max(1,int(statement_timeout_seconds*1000))
    def _begin(self, session) -> None:
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        session.execute(text("SELECT set_config('statement_timeout', :value, true)"),{"value":f"{self._timeout_ms}ms"})
    def readiness_check(self, deadline: datetime) -> bool:
        if not isinstance(deadline, datetime) or deadline.tzinfo is None or deadline.utcoffset() is None: return False
        try:
            with self._sessions() as session, session.begin():
                self._begin(session)
                return session.scalar(text("SELECT 1")) == 1
        except Exception:
            return False
    @staticmethod
    def _raise_db(exc: BaseException, correlation_id: str) -> None:
        if isinstance(exc, SqlAlchemyTimeoutError): code=PolicyRepositoryErrorCode.STORE_TIMEOUT
        elif isinstance(exc,(DataError,IntegrityError)): code=PolicyRepositoryErrorCode.DATA_INTEGRITY_VIOLATION
        else: code=PolicyRepositoryErrorCode.STORE_UNAVAILABLE
        raise PolicyRepositoryError(code=code,correlation_id=correlation_id,internal_cause=exc) from exc


class SqlAlchemyAuthorizationPolicyRepository(_PostgresAdapter):
    """Re-materialize built-in/custom role permissions on every evaluation."""

    def resolve_effective_permissions(self, request: PolicyMaterializationRequest) -> EffectivePermissionSet:
        try:
            with self._sessions() as session, session.begin():
                self._begin(session)
                roles, permissions, membership_version = self._snapshot(session, request)
                return EffectivePermissionSet(
                    permission_codes=permissions, role_codes=tuple(x.role_code for x in roles),
                    principal_kind=request.principal_kind, membership_id=request.membership_id,
                    permission_registry_version=PERMISSION_REGISTRY_VERSION,
                    tenant_policy_version=request.tenant_policy_version,
                    role_assignment_version=membership_version,
                    role_set_digest=request.role_set_digest, materialized_at=_utc(request.current_time),
                )
        except PolicyRepositoryError: raise
        except (SqlAlchemyTimeoutError,DataError,IntegrityError,OperationalError,InterfaceError,DisconnectionError,SQLAlchemyError) as exc:
            self._raise_db(exc,request.correlation_id)
        except (KeyError,TypeError,ValueError) as exc:
            raise PolicyRepositoryError(code=PolicyRepositoryErrorCode.DATA_INTEGRITY_VIOLATION,correlation_id=request.correlation_id,internal_cause=exc) from exc

    def resolve_role_assignments(self, request: PolicyMaterializationRequest) -> tuple[ResolvedPolicyRole,...]:
        try:
            with self._sessions() as session, session.begin():
                self._begin(session); roles, _, _ = self._snapshot(session,request); return roles
        except PolicyRepositoryError: raise
        except Exception as exc:
            self._raise_db(exc,request.correlation_id)

    def validate_registry_versions(self, request: PolicyMaterializationRequest) -> None:
        self.resolve_effective_permissions(request)

    def resolve_tenant_policy_version(self, tenant_id: uuid.UUID, *, correlation_id: str) -> int:
        try:
            with self._sessions() as session,session.begin():
                self._begin(session); tenant=session.get(SecurityTenant,tenant_id)
                if tenant is None: raise PolicyRepositoryError(code=PolicyRepositoryErrorCode.RESOURCE_NOT_FOUND,correlation_id=correlation_id)
                if tenant.status!="ACTIVE" or tenant.policy_version<=0: raise PolicyRepositoryError(code=PolicyRepositoryErrorCode.DATA_INTEGRITY_VIOLATION,correlation_id=correlation_id)
                return tenant.policy_version
        except PolicyRepositoryError: raise
        except Exception as exc: self._raise_db(exc,correlation_id)

    def _snapshot(self,session,request:PolicyMaterializationRequest):
        membership=session.get(SecurityMembership,request.membership_id)
        if membership is None or membership.principal_id!=request.principal_id or membership.tenant_id!=request.tenant_id:
            raise PolicyRepositoryError(code=PolicyRepositoryErrorCode.PROOF_MISMATCH,correlation_id=request.correlation_id)
        tenant=session.get(SecurityTenant,request.tenant_id)
        if tenant is None or tenant.tenant_key!=request.tenant_key: raise PolicyRepositoryError(code=PolicyRepositoryErrorCode.PROOF_MISMATCH,correlation_id=request.correlation_id)
        if tenant.policy_version!=request.tenant_policy_version: raise PolicyRepositoryError(code=PolicyRepositoryErrorCode.TENANT_POLICY_VERSION_MISMATCH,correlation_id=request.correlation_id)
        if request.permission_registry_version!=PERMISSION_REGISTRY_VERSION: raise PolicyRepositoryError(code=PolicyRepositoryErrorCode.REGISTRY_VERSION_MISMATCH,correlation_id=request.correlation_id)
        assigned=tuple(session.scalars(select(SecurityRole).join(SecurityMembershipRole,SecurityMembershipRole.role_id==SecurityRole.id).where(SecurityMembershipRole.membership_id==membership.id).order_by(SecurityRole.role_code)))
        if not assigned or tuple(x.role_code for x in assigned)!=request.roles: raise PolicyRepositoryError(code=PolicyRepositoryErrorCode.UNKNOWN_ROLE,correlation_id=request.correlation_id)
        if any(x.tenant_id!=tenant.id for x in assigned): raise PolicyRepositoryError(code=PolicyRepositoryErrorCode.DATA_INTEGRITY_VIOLATION,correlation_id=request.correlation_id)
        if any(x.status!="ACTIVE" for x in assigned): raise PolicyRepositoryError(code=PolicyRepositoryErrorCode.UNKNOWN_ROLE,correlation_id=request.correlation_id)
        role_ids=tuple(x.id for x in assigned)
        rows=tuple(session.execute(select(SecurityRolePermission.role_id,SecurityPermission).join(SecurityPermission,SecurityPermission.permission_code==SecurityRolePermission.permission_code,isouter=True).where(SecurityRolePermission.role_id.in_(role_ids))))
        by_role={rid:[] for rid in role_ids}
        for rid,permission in rows:
            if permission is None or rid not in by_role: raise PolicyRepositoryError(code=PolicyRepositoryErrorCode.UNKNOWN_PERMISSION,correlation_id=request.correlation_id)
            by_role[rid].append(permission)
        if any(not by_role[rid] for rid in role_ids): raise PolicyRepositoryError(code=PolicyRepositoryErrorCode.UNKNOWN_PERMISSION,correlation_id=request.correlation_id)
        permissions=tuple(p for rid in role_ids for p in by_role[rid])
        if any(p.permission_registry_version!=PERMISSION_REGISTRY_VERSION for p in permissions): raise PolicyRepositoryError(code=PolicyRepositoryErrorCode.REGISTRY_VERSION_MISMATCH,correlation_id=request.correlation_id)
        if request.principal_kind is IdentityKind.SERVICE and any(not p.service_allowed for p in permissions): raise PolicyRepositoryError(code=PolicyRepositoryErrorCode.DATA_INTEGRITY_VIOLATION,correlation_id=request.correlation_id)
        if request.principal_kind is IdentityKind.HUMAN and any(not p.human_allowed for p in permissions): raise PolicyRepositoryError(code=PolicyRepositoryErrorCode.DATA_INTEGRITY_VIOLATION,correlation_id=request.correlation_id)
        records=tuple({"role_id":str(role.id),"role_code":role.role_code,"role_version":role.version,"permission_codes":tuple(sorted({p.permission_code for p in by_role[role.id]}))} for role in assigned)
        digest=hashlib.sha256(json.dumps(records,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
        reference=f"policy-ref/v1:{tenant.policy_version}:{membership.id}:{membership.version}:{PERMISSION_REGISTRY_VERSION}:{digest}"
        if digest!=request.role_set_digest or reference!=request.permission_resolution_reference: raise PolicyRepositoryError(code=PolicyRepositoryErrorCode.PROOF_MISMATCH,correlation_id=request.correlation_id)
        resolved=tuple(ResolvedPolicyRole(role.id,role.role_code,role.version,membership.version,tuple(sorted({p.permission_code for p in by_role[role.id]}))) for role in assigned)
        return resolved,tuple(sorted({p.permission_code for p in permissions})),membership.version


class SqlAlchemySyntheticSecurityScopeResolver(_PostgresAdapter):
    def __init__(self,session_factory,*,codec:ResourceSecurityVersionCodec|None=None,statement_timeout_seconds:float=2.0)->None:
        super().__init__(session_factory,statement_timeout_seconds=statement_timeout_seconds); self._codec=codec or ResourceSecurityVersionCodec()
    def resolve_system_scope(self,*,current_time:datetime,correlation_id:str)->ResourceSecurityScope:
        now=_utc(current_time); values={"resource_type":PolicyScopeType.SYSTEM,"resource_id":"system"}
        return ResourceSecurityScope(PolicyScopeType.SYSTEM,"system",None,None,None,None,None,self._codec.scope_version(PolicyScopeType.SYSTEM,values),PolicyExistenceHiding.NONE,ResourceOwnershipState.SYSTEM_OWNED,now)
    def resolve_tenant_scope(self,*,tenant_key:str,identity_tenant_key:str,expected_tenant_policy_version:int,current_time:datetime,correlation_id:str)->ResourceSecurityScope:
        if tenant_key!=identity_tenant_key: raise PolicyRepositoryError(code=PolicyRepositoryErrorCode.RESOURCE_NOT_FOUND,correlation_id=correlation_id)
        try:
            with self._sessions() as session,session.begin():
                self._begin(session); tenant=session.scalar(select(SecurityTenant).where(SecurityTenant.tenant_key==tenant_key,SecurityTenant.status=="ACTIVE"))
                if tenant is None: raise PolicyRepositoryError(code=PolicyRepositoryErrorCode.RESOURCE_NOT_FOUND,correlation_id=correlation_id)
                if tenant.policy_version!=expected_tenant_policy_version: raise PolicyRepositoryError(code=PolicyRepositoryErrorCode.TENANT_POLICY_VERSION_MISMATCH,correlation_id=correlation_id)
                values={"resource_type":PolicyScopeType.TENANT,"tenant_id":tenant.id,"tenant_key":tenant.tenant_key,"tenant_policy_version":tenant.policy_version}
                return ResourceSecurityScope(PolicyScopeType.TENANT,tenant.tenant_key,tenant.tenant_key,None,None,None,None,self._codec.scope_version(PolicyScopeType.TENANT,values),PolicyExistenceHiding.NONE,ResourceOwnershipState.TENANT_OWNED,_utc(current_time))
        except PolicyRepositoryError: raise
        except Exception as exc: self._raise_db(exc,correlation_id)
    def resolve_company_period_scope(self,*,company_id:uuid.UUID,financial_period_id:uuid.UUID,expected_tenant_key:str,current_time:datetime,correlation_id:str)->ResourceSecurityScope:
        try:
            with self._sessions() as session,session.begin():
                self._begin(session)
                row=session.execute(select(Company,FinancialPeriod).join(FinancialPeriod,FinancialPeriod.company_id==Company.id).join(SecurityTenant,SecurityTenant.id==Company.tenant_id).where(Company.id==company_id,FinancialPeriod.id==financial_period_id,SecurityTenant.tenant_key==expected_tenant_key,SecurityTenant.status=="ACTIVE")).one_or_none()
                if row is None: raise PolicyRepositoryError(code=PolicyRepositoryErrorCode.RESOURCE_NOT_FOUND,correlation_id=correlation_id)
                company,period=row; rid=f"cp1:{company.id}:{period.id}"
                values={"resource_type":PolicyScopeType.COMPANY_PERIOD,"resource_id":rid,"company_id":company.id,"period_id":period.id,"company_updated_at":_utc(company.updated_at),"period_updated_at":_utc(period.updated_at)}
                return ResourceSecurityScope(PolicyScopeType.COMPANY_PERIOD,rid,expected_tenant_key,company.id,period.id,None,None,self._codec.scope_version(PolicyScopeType.COMPANY_PERIOD,values),PolicyExistenceHiding.NONE,ResourceOwnershipState.TENANT_OWNED,_utc(current_time))
        except PolicyRepositoryError: raise
        except Exception as exc: self._raise_db(exc,correlation_id)


class SqlAlchemyResourceSecurityRepository(_PostgresAdapter):
    """Tenant-qualified durable resource resolution; never performs an unscoped probe."""
    def __init__(self,session_factory,*,codec:ResourceSecurityVersionCodec|None=None,statement_timeout_seconds:float=2.0)->None:
        super().__init__(session_factory,statement_timeout_seconds=statement_timeout_seconds); self._codec=codec or ResourceSecurityVersionCodec()
    def resolve_durable_scope(self,*,resource_type:PolicyScopeType,resource_id:uuid.UUID|str,expected_tenant_key:str,current_time:datetime,correlation_id:str)->ResourceSecurityScope:
        if resource_type not in set(PolicyScopeType)-{PolicyScopeType.SYSTEM,PolicyScopeType.TENANT,PolicyScopeType.COMPANY_PERIOD}: raise PolicyRepositoryError(code=PolicyRepositoryErrorCode.DATA_INTEGRITY_VIOLATION,correlation_id=correlation_id)
        try:
            with self._sessions() as session,session.begin():
                self._begin(session); scope=self._resolve(session,resource_type,resource_id,expected_tenant_key,_utc(current_time),correlation_id)
                if scope is None: raise PolicyRepositoryError(code=PolicyRepositoryErrorCode.RESOURCE_NOT_FOUND,correlation_id=correlation_id)
                return scope
        except PolicyRepositoryError: raise
        except (KeyError,TypeError,ValueError) as exc: raise PolicyRepositoryError(code=PolicyRepositoryErrorCode.DATA_INTEGRITY_VIOLATION,correlation_id=correlation_id,internal_cause=exc) from exc
        except Exception as exc: self._raise_db(exc,correlation_id)
    def _resolve(self,s,t,rid,tenant_key,now,cid):
        hiding=PolicyExistenceHiding.ALWAYS_HIDE_DENIAL
        if t is PolicyScopeType.COMPANY:
            row=s.execute(select(Company,SecurityTenant).join(SecurityTenant,SecurityTenant.id==Company.tenant_id).where(Company.id==rid,SecurityTenant.tenant_key==tenant_key)).one_or_none()
            if not row:return None
            obj,tenant=row; vals={"resource_type":t,"id":obj.id,"tenant_id":tenant.id,"updated_at":_utc(obj.updated_at)}
            return ResourceSecurityScope(t,obj.id,tenant_key,obj.id,None,None,None,self._codec.scope_version(t,vals),hiding,ResourceOwnershipState.TENANT_OWNED,now)
        if t is PolicyScopeType.FINANCIAL_PERIOD:
            row=s.execute(select(FinancialPeriod,Company).join(Company,Company.id==FinancialPeriod.company_id).join(SecurityTenant,SecurityTenant.id==Company.tenant_id).where(FinancialPeriod.id==rid,SecurityTenant.tenant_key==tenant_key)).one_or_none()
            if not row:return None
            obj,company=row; vals={"resource_type":t,"id":obj.id,"company_id":company.id,"status":obj.status,"updated_at":_utc(obj.updated_at)}
            return ResourceSecurityScope(t,obj.id,tenant_key,company.id,obj.id,None,None,self._codec.scope_version(t,vals),hiding,ResourceOwnershipState.TENANT_OWNED,now)
        if t is PolicyScopeType.DOCUMENT:
            row=s.execute(select(FinancialDocument).join(Company,Company.id==FinancialDocument.company_id).join(SecurityTenant,SecurityTenant.id==Company.tenant_id).where(FinancialDocument.id==rid,SecurityTenant.tenant_key==tenant_key)).scalar_one_or_none()
            if not row:return None
            vals={"resource_type":t,"id":row.id,"company_id":row.company_id,"period_id":row.period_id,"checksum":bytes.fromhex(row.checksum),"processing_status":row.processing_status,"processed_at":(_utc(row.processed_at) if row.processed_at else None)}
            return ResourceSecurityScope(t,row.id,tenant_key,row.company_id,row.period_id,None,None,self._codec.scope_version(t,vals),hiding,ResourceOwnershipState.TENANT_OWNED,now)
        if t in {PolicyScopeType.ANALYSIS_RESULT,PolicyScopeType.TRIAL_BALANCE}:
            row=s.execute(select(FinancialAnalysisResult).join(Company,Company.id==FinancialAnalysisResult.company_id).join(SecurityTenant,SecurityTenant.id==Company.tenant_id).where(FinancialAnalysisResult.id==rid,SecurityTenant.tenant_key==tenant_key)).scalar_one_or_none()
            if not row:return None
            if t is PolicyScopeType.TRIAL_BALANCE and row.analysis_type.value!="trial_balance": raise PolicyRepositoryError(code=PolicyRepositoryErrorCode.DATA_INTEGRITY_VIOLATION,correlation_id=cid)
            if not row.canonical_result_digest: raise PolicyRepositoryError(code=PolicyRepositoryErrorCode.DATA_INTEGRITY_VIOLATION,correlation_id=cid)
            vals={"resource_type":t,"id":row.id,"company_id":row.company_id,"period_id":row.period_id,"status":row.status,"canonical_result_digest":bytes.fromhex(row.canonical_result_digest),"completed_at":(_utc(row.completed_at) if row.completed_at else None)}
            if t is PolicyScopeType.TRIAL_BALANCE: vals.update({"analysis_type":row.analysis_type,"source_mode":row.source_mode})
            return ResourceSecurityScope(t,row.id,tenant_key,row.company_id,row.period_id,None,None,self._codec.scope_version(t,vals),hiding,ResourceOwnershipState.TENANT_OWNED,now)
        if t is PolicyScopeType.BULK_UPLOAD_BATCH:
            row=s.execute(select(BulkUploadBatch).join(SecurityTenant,SecurityTenant.id==BulkUploadBatch.tenant_id).where(BulkUploadBatch.id==rid,SecurityTenant.tenant_key==tenant_key)).scalar_one_or_none()
            if not row:return None
            vals={"resource_type":t,"id":row.id,"tenant_id":row.tenant_id,"status":row.status,"total_file_count":row.total_file_count,"classified_file_count":row.classified_file_count,"unclassified_file_count":row.unclassified_file_count,"duplicate_file_count":row.duplicate_file_count,"completed_at":(_utc(row.completed_at) if row.completed_at else None),"confirmed_at":(_utc(row.confirmed_at) if row.confirmed_at else None)}
            return ResourceSecurityScope(t,row.id,tenant_key,None,None,None,None,self._codec.scope_version(t,vals),hiding,ResourceOwnershipState.TENANT_OWNED,now)
        if t is PolicyScopeType.ANALYSIS_RUN:
            row=s.execute(select(AnalysisRunScopeClaim,OrchestrationRun).join(OrchestrationRun,OrchestrationRun.id==AnalysisRunScopeClaim.persisted_run_id).where(AnalysisRunScopeClaim.run_id==rid,AnalysisRunScopeClaim.tenant_id==tenant_key)).one_or_none()
            if not row:return None
            claim,run=row; owner=claim.initiating_subject_id
            if not owner: raise PolicyRepositoryError(code=PolicyRepositoryErrorCode.DATA_INTEGRITY_VIOLATION,correlation_id=cid)
            ref="srh1:k0:"+hashlib.sha256(owner.encode()).hexdigest()
            vals={"resource_type":t,"claim_id":claim.claim_id,"run_id":claim.run_id,"company_id":claim.company_id,"financial_period_id":claim.financial_period_id,"tenant_key":claim.tenant_id,"initiating_subject_reference":ref,"claim_version":claim.version,"claim_status":_enum(claim.status),"terminal_content_digest":_hex(run.terminal_content_digest)}
            return ResourceSecurityScope(t,claim.run_id,tenant_key,claim.company_id,claim.financial_period_id,owner,None,self._codec.scope_version(t,vals),hiding,ResourceOwnershipState.SUBJECT_OWNED,now)
        if t is PolicyScopeType.EXECUTION:
            row=s.execute(select(OrchestrationEngineExecution,AnalysisRunScopeClaim).join(OrchestrationRun,OrchestrationRun.id==OrchestrationEngineExecution.run_id).join(AnalysisRunScopeClaim,AnalysisRunScopeClaim.persisted_run_id==OrchestrationRun.id).where(OrchestrationEngineExecution.id==rid,AnalysisRunScopeClaim.tenant_id==tenant_key)).one_or_none()
            if not row:return None
            execution,claim=row; owner=claim.initiating_subject_id
            if not owner: raise PolicyRepositoryError(code=PolicyRepositoryErrorCode.DATA_INTEGRITY_VIOLATION,correlation_id=cid)
            vals={"resource_type":t,"execution_id":execution.id,"orchestration_run_id":execution.run_id,"engine_code":_enum(execution.engine_code),"status":_enum(execution.status),"input_fingerprint":_hex(execution.input_fingerprint),"owner_content_digest":_hex(execution.owner_content_digest),"claim_version":claim.version}
            return ResourceSecurityScope(t,execution.id,tenant_key,claim.company_id,claim.financial_period_id,owner,None,self._codec.scope_version(t,vals),hiding,ResourceOwnershipState.SUBJECT_OWNED,now)
        raise PolicyRepositoryError(code=PolicyRepositoryErrorCode.DATA_INTEGRITY_VIOLATION,correlation_id=cid)
