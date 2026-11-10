async def lookup(self, ref, params):
        if (set(params) - {'session_id', 'submission_id', 'include_result'}
                or not isinstance(params.get('submission_id'), str)
                or not params['submission_id'] or len(params['submission_id']) > 256):
            raise RuntimeStoreError('invalid_params')
        self.authority.authorize(self.actor, ref, 'session:read')
        from hermes_state_runtime import find_session_admission
        saved = await asyncio.to_thread(find_session_admission, self.authority.db,
            principal_id=self.actor.subject, session_id=ref.session_id, request_id=params['submission_id'])
        import os
        out = {'process_scope_supported': os.name == 'nt' and os.environ.get('MESH_LOCAL_PROCESS_SCOPE') == '1',
               'found': saved is not None, 'session_id': ref.session_id, 'submission_id': params['submission_id'],
            'outcome': saved.get('outcome') if saved is not None else None}
        # Read the already committed policy, never refresh it or resolve a new provider.
        from hermes_state_local import local_receipt
        from gateway.session_policy import restore_policy
        from gateway.mesh_assignment_process import describe_profile
        local = await asyncio.to_thread(local_receipt, self.authority.db, ref.session_id)
        if local is not None:
            out['profile_contract'] = describe_profile(restore_policy(local['policy']), self.authority)
        if saved is not None:
            out['receipt'] = await self.receipt(ref, {'admission_id': saved['admission_id'],
                'include_result': params.get('include_result') is True})
            scope = getattr(self.authority, '_mesh_assignment_processes', {}).get(saved['admission_id'])
            if scope is not None:
                identity = scope.identity
                out['profile_contract'] = scope.profile_contract
                if (identity['principalId'] != self.actor.subject or identity['sessionId'] != ref.session_id
                        or identity['admissionId'] != saved['admission_id']
                        or identity['profileId'] != str(self.authority.profile_id)
                        or identity['executionGeneration'] != out['receipt'].get('execution_generation')):
                    raise RuntimeStoreError('assignment_process_mismatch')
                observed = await asyncio.to_thread(scope.observe)
                out['process_scope'] = {
                    'admission_id': identity['admissionId'], 'session_id': identity['sessionId'],
                    'profile_id': identity['profileId'], 'execution_generation': identity['executionGeneration'],
                    'sealed': observed['assignmentLaunchSealed'] and observed['sealed'],
                    'state': observed['state'], 'active_processes': observed.get('activeProcesses'),
                    'root_ended': observed.get('allRootsEnded', False),
                    'process_tree_ended': observed['processTreeEnded'],
                    'termination_requested': observed['terminationRequested'], 'writer_quiescence': False,
                    'reason': observed.get('reason')}
                from gateway.mesh_assignment_process import observe_retirement
                out['process_scope'].update(await observe_retirement(self.authority, scope))
        return out
