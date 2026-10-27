from bob.api import assays, auth, mappings, projects, recipes, synbiohub, workspaces

routers = [auth.router, workspaces.router, workspaces.invitations_router, projects.router, assays.router, mappings.router, recipes.router, synbiohub.router]
