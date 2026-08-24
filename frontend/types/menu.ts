export interface Menu {
    menu_id: number;
    restaurant_id: number;
    name: string;
    description: string | null;
}

export interface MenuCreate {
    name: string;
    description?: string | null;
}

export interface MenuUpdate {
    name?: string;
    description?: string | null;
}