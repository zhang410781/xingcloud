import request from '../request'

export const getResourceTypes = () => request.get('/resource-center/types/')
export const getResources = (params) => request.get('/resource-center/resources/', { params })
export const getResource = (id) => request.get(`/resource-center/resources/${id}/`)
export const createResource = (data) => request.post('/resource-center/resources/', data)
export const updateResource = (id, data) => request.patch(`/resource-center/resources/${id}/`, data)
export const deleteResource = (id) => request.delete(`/resource-center/resources/${id}/`)
export const getResourceSummary = () => request.get('/resource-center/resources/summary/')
export const getResourceTopology = (params) => request.get('/resource-center/resources/topology/', { params })
export const getResourceBusinessContexts = () => request.get('/resource-center/resources/business-context-options/')
export const getResourceRuntime = (id, params) => request.get(`/resource-center/resources/${id}/runtime/`, { params })
export const getResourceChanges = (id) => request.get(`/resource-center/resources/${id}/changes/`)

export const getResourceContacts = (params) => request.get('/resource-center/contacts/', { params })
export const createResourceContact = (data) => request.post('/resource-center/contacts/', data)
export const deleteResourceContact = (id) => request.delete(`/resource-center/contacts/${id}/`)

export const getDiscoverySources = () => request.get('/resource-center/discovery-sources/')
export const updateDiscoverySource = (id, data) => request.patch(`/resource-center/discovery-sources/${id}/`, data)
export const previewDiscoverySource = (id) => request.post(`/resource-center/discovery-sources/${id}/preview/`)
export const runDiscoverySource = (id, wait = false) => request.post(`/resource-center/discovery-sources/${id}/run/?wait=${wait}`)
export const getDiscoveryRuns = (params) => request.get('/resource-center/discovery-runs/', { params })
