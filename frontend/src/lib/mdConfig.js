// Field specs per master entity (BRD Addendum §4). [key, label, type, required, options]
// types: text | code | date | number | bool | select (options) | lookup (lookup TYPE) | project | employee | store
export const ENTITIES = {
  projects: {
    label: "Projects", keyLabel: "Project #", cols: ["number", "name", "client", "project_type", "status"],
    fields: [["number", "Project Number", "code", true], ["name", "Project Name", "text", true], ["client", "Business Unit / Org", "text", false],
      ["customer", "Customer", "text"], ["project_type", "Project Type", "lookup", false, "PROJECT_TYPE"], ["currency", "Project Currency", "select", false, ["USD", "EUR", "GBP", "AED", "INR"]],
      ["start_date", "Start Date", "date"], ["end_date", "End Date", "date"], ["project_manager", "Project Manager", "employee"],
      ["status", "Project Status", "select", true, ["Draft", "Active", "On Hold", "Closed"]], ["site", "Site / Location (LO)", "text"]],
  },
  tasks: {
    label: "Tasks / WBS", keyLabel: "Task #", cols: ["project_number", "number", "name", "parent_task", "chargeable", "status"],
    fields: [["project_number", "Project", "project", true], ["number", "Task Number", "code", true], ["name", "Task Name", "text", true],
      ["parent_task", "Parent Task #", "text"], ["chargeable", "Chargeable", "select", false, ["Y", "N"]], ["start_date", "Start Date", "date"], ["end_date", "End Date", "date"],
      ["task_manager", "Task Manager", "employee"], ["allowed_types", "Allowed Resource Types (LO)", "select", false, ["", "Labor", "Equipment", "Material", "Labor+Equipment"]],
      ["status", "Task Status", "select", true, ["Active", "Closed"]]],
  },
  employees: {
    label: "Employees", keyLabel: "Employee #", cols: ["number", "name", "worker_type", "trade", "grade", "status"],
    fields: [["number", "Employee Number", "code", true], ["name", "Full Name", "text", true],
      ["worker_type", "Worker Type", "select", false, ["Employee", "Contractor", "Subcontractor"]], ["subcontractor_firm", "Subcontractor Firm", "text"],
      ["trade", "Craft / Job", "lookup", false, "CRAFT"], ["grade", "Grade (drives labor rate)", "lookup", true, "GRADE"], ["home_org", "Home Org", "text"],
      ["supervisor", "Supervisor / Foreman (LO)", "employee"], ["hire_date", "Hire Date", "date"], ["termination_date", "Termination Date", "date"],
      ["badge_id", "Badge / Swipe ID (LO)", "text"], ["email", "Email (LO)", "text"], ["mobile", "Mobile (LO)", "text"], ["status", "Status", "select", false, ["Active", "Inactive"]]],
  },
  equipment: {
    label: "Equipment", keyLabel: "Asset ID", cols: ["number", "name", "cls", "ownership", "availability", "status"],
    fields: [["number", "Asset ID", "code", true], ["name", "Description", "text", true], ["cls", "Equipment Class (drives rate)", "lookup", true, "EQUIPMENT_CLASS"],
      ["type", "Equipment Type", "text"], ["ownership", "Ownership", "select", false, ["Owned", "Rented", "Leased"]], ["vendor", "Vendor", "text"],
      ["make", "Make", "text"], ["model", "Model", "text"], ["serial_no", "Serial No", "text"], ["organization", "Nonlabor Resource Org", "text"],
      ["default_operator", "Default Operator (LO)", "employee"], ["meter_type", "Meter Type", "select", false, ["None", "Hours", "Km"]],
      ["current_project", "Current Project (LO)", "project"], ["availability", "Availability", "select", false, ["Available", "In Use", "Under Maintenance", "Disposed"]],
      ["status", "Status", "select", false, ["Active", "Inactive"]]],
  },
  items: {
    label: "Items & Unit Cost", keyLabel: "Item code", cols: ["number", "description", "uom", "category", "unit_cost", "status"],
    fields: [["number", "Item Code", "code", true], ["description", "Description", "text", true], ["uom", "Primary UOM", "lookup", true, "UOM"],
      ["category", "Item Category", "lookup", false, "ITEM_CATEGORY"], ["item_type", "Item Type", "select", false, ["Bulk", "Engineered", "Consumable"]],
      ["unit_cost", "Unit Cost (USD per UOM)", "number"], ["cost_effective_from", "Cost Effective From", "date"], ["default_store", "Default Store (LO)", "store"],
      ["lot_controlled", "Lot / Serial Controlled", "select", false, ["N", "Y"]], ["status", "Status", "select", false, ["Active", "Inactive"]]],
  },
  stores: {
    label: "Stores / Locations", keyLabel: "Store code", cols: ["code", "name", "store_type", "linked_projects", "status"],
    fields: [["code", "Store Code", "code", true], ["name", "Store Name", "text", true], ["store_type", "Store Type", "select", true, ["Central Warehouse", "Site Store", "Laydown Yard"]],
      ["linked_projects", "Linked Project(s), comma separated", "text"], ["address", "Address", "text"], ["store_keeper", "Store Keeper", "employee"],
      ["status", "Status", "select", false, ["Active", "Inactive"]]],
  },
  lookups: {
    label: "Lookups", keyLabel: "Code", cols: ["type", "code", "meaning", "description", "status"],
    fields: [["type", "Lookup Type", "select", true, ["CRAFT", "GRADE", "EQUIPMENT_CLASS", "UOM", "ITEM_CATEGORY", "BONUS_TYPE", "PROJECT_TYPE"]],
      ["code", "Code", "code", true], ["meaning", "Meaning", "text", true], ["description", "Description", "text"], ["order", "Display Order", "number"],
      ["status", "Status", "select", false, ["Active", "Inactive"]]],
  },
};
