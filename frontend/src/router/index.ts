import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/login' },
    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue'), meta: { guest: true } },
    {
      path: '/change-password',
      name: 'change-password',
      component: () => import('@/views/ChangePasswordView.vue'),
      meta: { requiresAuth: true },
    },
    { path: '/admin', redirect: '/admin/stats' },
    {
      path: '/admin/stats',
      name: 'admin-stats',
      component: () => import('@/views/admin/StatsView.vue'),
      meta: { requiresAuth: true, roles: ['admin', 'super_admin'] },
    },
    {
      path: '/admin/users',
      name: 'admin-users',
      component: () => import('@/views/admin/UserManageView.vue'),
      meta: { requiresAuth: true, roles: ['admin', 'super_admin'] },
    },
    {
      path: '/admin/qc-tasks',
      name: 'admin-qc-tasks',
      component: () => import('@/views/admin/QcTaskManageView.vue'),
      meta: { requiresAuth: true, roles: ['admin', 'super_admin'] },
    },
    {
      path: '/admin/exports',
      name: 'admin-exports',
      component: () => import('@/views/admin/ExportManageView.vue'),
      meta: { requiresAuth: true, roles: ['admin', 'super_admin'] },
    },
    {
      path: '/qc/tasks',
      name: 'qc-tasks',
      component: () => import('@/views/qc/QcIndexView.vue'),
      meta: { requiresAuth: true, roles: ['qc'] },
    },
    {
      path: '/qc/my-tasks',
      name: 'qc-my-tasks',
      component: () => import('@/views/qc/QcIndexView.vue'),
      meta: { requiresAuth: true, roles: ['qc'] },
    },
    {
      path: '/qc/completed',
      name: 'qc-completed',
      component: () => import('@/views/qc/QcIndexView.vue'),
      meta: { requiresAuth: true, roles: ['qc'] },
    },
    {
      path: '/qc/review/:id',
      name: 'qc-review',
      component: () => import('@/views/qc/QcIndexView.vue'),
      meta: { requiresAuth: true, roles: ['qc'] },
    },
  ],
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.name === 'change-password' && auth.isLoggedIn && !auth.user?.mustChangePassword) {
    return auth.user?.homePath || '/admin/stats'
  }
  if (to.meta.guest && auth.isLoggedIn) {
    return auth.user?.homePath || '/admin/stats'
  }
  if (to.meta.requiresAuth) {
    if (!auth.isLoggedIn) return { path: '/login', query: { redirect: to.fullPath } }
    if (auth.user?.mustChangePassword && to.name !== 'change-password') {
      return { path: '/change-password' }
    }
    const roles = to.meta.roles as string[] | undefined
    if (roles && auth.user) {
      // A user can hold both QC and admin; role is only the display/default role.
      const held = auth.user.roles?.length ? auth.user.roles : [auth.user.role]
      if (!roles.some((role) => held.includes(role))) {
        return auth.user.homePath || '/login'
      }
    }
  }
  return true
})

export default router

